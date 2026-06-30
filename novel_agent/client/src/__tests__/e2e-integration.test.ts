/**
 * 端到端联动集成测试
 *
 * 使用真实的 createSseHandler + Pinia Store，验证聊天 → SSE → 编辑器联动。
 * 章节生成专项回归见 chapter-generation-regression.test.ts。
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useEditorStore, useChatStore } from '@/stores'
import { createSseHandler } from '@/composables/useSseHandler'
import type { SseEvent } from '@/types'

// 模拟 API 层
vi.mock('@/api', () => ({
  chatStream: vi.fn(),
  resumeStream: vi.fn(),
  getState: vi.fn(),
  getChapterContent: vi.fn(),
  updateChapter: vi.fn(),
  addChapter: vi.fn(),
  updateField: vi.fn(),
  deleteChapter: vi.fn(),
  getChatHistory: vi.fn(),
  clearChat: vi.fn(),
}))

function makeHandleEvent(
  chatStore: ReturnType<typeof useChatStore>,
  editorStore: ReturnType<typeof useEditorStore>,
) {
  return createSseHandler(chatStore, editorStore, {
    onError: (evt) => { throw new Error(evt.error || '未知错误') },
  })
}

describe('E2E: Chat input → SSE events → Editor state', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    const { getState } = await import('@/api')
    vi.mocked(getState).mockResolvedValue({
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试', total_chapters: 0 },
      outline: null,
      chapters: [],
      messages: [],
    })
  })

  it('chitchat flow: user input → token events → streaming content → agent message', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    // 模拟用户输入
    chatStore.addUserMessage('你好')
    chatStore.streamingContent = ''
    chatStore.reasoningContent = ''
    chatStore.showThinking = false
    editorStore.startGeneration()

    // 模拟 SSE 事件流
    const events: SseEvent[] = [
      { type: 'reasoning', token: '用户在打招呼' },
      { type: 'token', token: '你好！' },
      { type: 'token', token: '我是墨灵。' },
      { type: 'task_complete', summary: '已回复' },
      { type: 'done' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    // 验证聊天状态
    expect(chatStore.streamingContent).toBe('你好！我是墨灵。')
    expect(chatStore.showThinking).toBe(true)
    expect(chatStore.reasoningContent).toBe('用户在打招呼')
    expect(chatStore.thinkingCollapsed).toBe(true) // token 到达后折叠思考

    // 模拟流结束后保存为消息
    if (chatStore.streamingContent) {
      chatStore.addAgentMessage(chatStore.streamingContent, chatStore.reasoningContent || undefined)
    }
    chatStore.streamingContent = ''
    chatStore.reasoningContent = ''
    chatStore.showThinking = false
    editorStore.stopGeneration()

    // 验证最终状态
    expect(chatStore.messages.length).toBe(2) // user + agent
    expect(chatStore.messages[1].role).toBe('assistant')
    expect(chatStore.messages[1].content).toBe('你好！我是墨灵。')
    expect(chatStore.messages[1].thinking).toBe('用户在打招呼')
    expect(editorStore.isGenerating).toBe(false)
  })

  it('generate field flow: generate_start → tokens → generate_done → field_content', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    editorStore.editingField = 'settings_md_content'
    editorStore.fieldValues.settings_md_content = '旧设定'
    editorStore.startGeneration()

    const events: SseEvent[] = [
      { type: 'token', token: '正在生成设定...' },
      { type: 'generate_start', target: 'settings_md_content' },
      { type: 'generate_token', target: 'settings_md_content', token: '修仙' },
      { type: 'generate_token', target: 'settings_md_content', token: '世界' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'settings_md_content', content: '修仙世界，灵气为尊' },
      { type: 'task_complete', summary: '设定已生成' },
      { type: 'done' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    // 验证编辑器状态
    expect(editorStore.editingField).toBe('settings_md_content')
    expect(editorStore.fieldValues.settings_md_content).toBe('修仙世界，灵气为尊')
    expect(editorStore.mdPreviewMode).toBe(false)

    // 验证聊天内容
    expect(chatStore.streamingContent).toContain('正在生成设定')
    editorStore.stopGeneration()
  })

  it('generate chapter flow: generate_start → chapter_title → tokens → field_content', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    editorStore.startGeneration()

    const events: SseEvent[] = [
      { type: 'generate_start', target: 'chapter_new' },
      { type: 'chapter_title', title: '风起云涌' },
      { type: 'generate_token', target: 'chapter_new', token: '正文开始...' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'chapter_1', content: '正文开始...' },
      { type: 'task_complete', summary: '章节已生成' },
      { type: 'done' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    // 验证章节标题（generate_done 后会清空 pending）
    expect(editorStore.fieldValues['chapter_1']).toBe('正文开始...')
    expect(editorStore.streamingChapterContent).toBe('正文开始...')

    // field_content 切换到 chapter_1
    expect(editorStore.editingField).toBe('chapter_1')

    editorStore.stopGeneration()
  })

  it('generate with reset: generate_start → tokens → generate_reset → new tokens', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    editorStore.editingField = 'characters_md_content'
    editorStore.startGeneration()

    const events: SseEvent[] = [
      { type: 'generate_start', target: 'characters_md_content' },
      { type: 'generate_token', target: 'characters_md_content', token: '不满意的' },
      { type: 'generate_reset', target: 'characters_md_content' },
      { type: 'generate_start', target: 'characters_md_content' },
      { type: 'generate_token', target: 'characters_md_content', token: '新角色' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'characters_md_content', content: '新角色档案' },
      { type: 'task_complete', summary: '角色已生成' },
      { type: 'done' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    // reset 后内容被清空，然后重新生成
    expect(editorStore.fieldValues.characters_md_content).toBe('新角色档案')
    editorStore.stopGeneration()
  })
})

describe('E2E: field_content switches editor field', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('switches from settings to characters on field_content', () => {
    const editorStore = useEditorStore()
    const chatStore = useChatStore()

    editorStore.editingField = 'settings_md_content'
    editorStore.fieldValues.settings_md_content = '设定内容'
    editorStore.mdPreviewMode = true

    makeHandleEvent(chatStore, editorStore)(
      { type: 'field_content', target: 'characters_md_content', content: '角色档案' },
    )

    expect(editorStore.editingField).toBe('characters_md_content')
    expect(editorStore.fieldValues.characters_md_content).toBe('角色档案')
    expect(editorStore.mdPreviewMode).toBe(false)
  })

  it('switches from field to chapter on field_content', () => {
    const editorStore = useEditorStore()
    const chatStore = useChatStore()

    editorStore.editingField = 'settings_md_content'

    makeHandleEvent(chatStore, editorStore)(
      { type: 'field_content', target: 'chapter_5', content: '第5章内容' },
    )

    expect(editorStore.editingField).toBe('chapter_5')
    expect(editorStore.fieldValues['chapter_5']).toBe('第5章内容')
  })

  it('field_content for chapter_new sets editingField', () => {
    const editorStore = useEditorStore()
    const chatStore = useChatStore()

    makeHandleEvent(chatStore, editorStore)(
      { type: 'field_content', target: 'chapter_new', content: '新章节内容' },
    )

    expect(editorStore.editingField).toBe('chapter_new')
    expect(editorStore.fieldValues['chapter_new']).toBe('新章节内容')
  })
})

describe('E2E: Multi-agent handoff flow', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('handoff → subagent_tool_call → generate flow', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    chatStore.addUserMessage('生成写作设定')
    chatStore.streamingContent = ''
    editorStore.startGeneration()

    const events: SseEvent[] = [
      { type: 'reasoning', token: '用户要生成设定' },
      { type: 'handoff', agent: 'creator' },
      { type: 'subagent_tool_call', name: 'generate_settings' },
      { type: 'generate_start', target: 'settings_md_content' },
      { type: 'generate_token', target: 'settings_md_content', token: '修仙世界' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'settings_md_content', content: '修仙世界，灵气为尊' },
      { type: 'task_complete', summary: '设定已生成' },
      { type: 'done' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    // handoff / subagent_tool_call 由 agent_activity 展示，createSseHandler 不写入 streamingContent
    expect(chatStore.reasoningContent).toBe('用户要生成设定')

    // 验证编辑器状态
    expect(editorStore.fieldValues.settings_md_content).toBe('修仙世界，灵气为尊')

    editorStore.stopGeneration()
  })

  it('plan_execute events do not break handler', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    chatStore.addUserMessage('帮我创建一本新小说的完整设定')
    chatStore.streamingContent = ''
    editorStore.startGeneration()

    const events: SseEvent[] = [
      { type: 'plan_generated', steps: [
        { description: '生成设定', agent: 'creator' },
        { description: '生成角色', agent: 'creator' },
      ]} as any,
      { type: 'plan_step_start', step: 0, description: '生成设定', agent: 'creator' } as any,
      { type: 'subagent_tool_call', name: 'generate_settings' },
      { type: 'plan_step_complete', step: 0, success: true } as any,
      { type: 'plan_step_start', step: 1, description: '生成角色', agent: 'creator' } as any,
      { type: 'subagent_tool_call', name: 'generate_characters' },
      { type: 'plan_step_complete', step: 1, success: true } as any,
      { type: 'plan_completed', total_steps: 2 } as any,
      { type: 'task_complete', summary: '所有步骤完成' },
      { type: 'done' },
    ]

    expect(() => {
      for (const evt of events) {
        makeHandleEvent(chatStore, editorStore)(evt)
      }
    }).not.toThrow()

    editorStore.stopGeneration()
  })
})

describe('E2E: Error handling flow', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('error event throws and is caught, added as agent message', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    chatStore.addUserMessage('测试')
    editorStore.startGeneration()

    try {
      makeHandleEvent(chatStore, editorStore)(
        { type: 'error', error: 'LLM 调用超时' },
      )
    } catch (e: any) {
      chatStore.addAgentMessage('出错了：' + (e.message || '未知错误'))
    }

    expect(chatStore.messages.length).toBe(2)
    expect(chatStore.messages[1].content).toContain('LLM 调用超时')

    editorStore.stopGeneration()
  })

  it('abort during streaming preserves partial content in editor', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    chatStore.addUserMessage('生成设定')
    chatStore.streamingContent = ''
    editorStore.startGeneration()

    // 模拟部分 SSE 事件后中断
    const events: SseEvent[] = [
      { type: 'generate_start', target: 'settings_md_content' },
      { type: 'generate_token', target: 'settings_md_content', token: '部分内容' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    // generate_token 写入独立生成缓冲
    expect(editorStore.generatingStreamContent).toBe('部分内容')

    // 模拟 abort：chatStore.streamingContent 可能为空
    if (chatStore.streamingContent) {
      chatStore.addAgentMessage(chatStore.streamingContent)
    }
    chatStore.streamingContent = ''
    chatStore.addAgentMessage('⏹ 已停止')
    editorStore.stopGeneration()

    const stopMsg = chatStore.messages.find(m => m.content === '⏹ 已停止')
    expect(stopMsg).toBeDefined()
    expect(editorStore.isGenerating).toBe(false)
  })
})

describe('E2E: Content history (undo/redo) with SSE events', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('push snapshot before generation, undo restores previous content', () => {
    const editorStore = useEditorStore()
    const chatStore = useChatStore()

    // 初始状态
    editorStore.editingField = 'settings_md_content'
    editorStore.fieldValues.settings_md_content = '旧设定'
    editorStore.pushContentSnapshot('生成前')

    // 模拟生成
    const events: SseEvent[] = [
      { type: 'generate_start', target: 'settings_md_content' },
      { type: 'generate_token', target: 'settings_md_content', token: '新设定' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'settings_md_content', content: '新设定' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    expect(editorStore.fieldValues.settings_md_content).toBe('新设定')

    // push 第二个 snapshot（生成后）
    editorStore.pushContentSnapshot('生成后')

    // 模拟 undo：回到第一个 snapshot
    const snapshot = editorStore.undoGeneration()
    expect(snapshot).not.toBeNull()
    expect(snapshot!.content).toBe('旧设定')
    expect(snapshot!.field).toBe('settings_md_content')
  })

  it('push snapshot, generate, undo, then redo', () => {
    const editorStore = useEditorStore()

    editorStore.editingField = 'characters_md_content'
    editorStore.fieldValues.characters_md_content = '旧角色'
    editorStore.pushContentSnapshot('初始')

    editorStore.fieldValues.characters_md_content = '新角色'
    editorStore.pushContentSnapshot('生成')

    // undo
    const undoSnap = editorStore.undoGeneration()
    expect(undoSnap!.content).toBe('旧角色')

    // redo
    const redoSnap = editorStore.redoGeneration()
    expect(redoSnap!.content).toBe('新角色')
  })
})

describe('E2E: Full chat → generate → save cycle', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('complete cycle: chat input → SSE stream → editor update → save', async () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    // 1. 用户输入
    chatStore.addUserMessage('生成写作设定')
    chatStore.streamingContent = ''
    chatStore.reasoningContent = ''
    chatStore.showThinking = false
    editorStore.startGeneration()

    // 2. SSE 事件流
    const events: SseEvent[] = [
      { type: 'reasoning', token: '需要生成设定' },
      { type: 'handoff', agent: 'creator' },
      { type: 'subagent_tool_call', name: 'generate_settings' },
      { type: 'generate_start', target: 'settings_md_content' },
      { type: 'generate_token', target: 'settings_md_content', token: '修仙世界' },
      { type: 'generate_token', target: 'settings_md_content', token: '，灵气为尊' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'settings_md_content', content: '修仙世界，灵气为尊' },
      { type: 'task_complete', summary: '设定已生成' },
      { type: 'done' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    // 3. 流结束，保存 agent 消息（handoff 等事件不写入 streamingContent，用 reasoning 归档）
    chatStore.addAgentMessage(
      chatStore.streamingContent || '设定已生成',
      chatStore.reasoningContent || undefined,
    )
    chatStore.streamingContent = ''
    chatStore.reasoningContent = ''
    chatStore.showThinking = false
    editorStore.stopGeneration()

    // 4. 验证聊天状态
    expect(chatStore.messages.length).toBe(2) // user + agent
    expect(chatStore.messages[0].role).toBe('user')
    expect(chatStore.messages[0].content).toBe('生成写作设定')
    expect(chatStore.messages[1].role).toBe('assistant')
    expect(chatStore.messages[1].thinking).toBe('需要生成设定')

    // 5. 验证编辑器状态
    expect(editorStore.editingField).toBe('settings_md_content')
    expect(editorStore.fieldValues.settings_md_content).toBe('修仙世界，灵气为尊')
    expect(editorStore.mdPreviewMode).toBe(false)
    expect(editorStore.isGenerating).toBe(false)

    // 6. 模拟保存（调用 API）
    const { updateField } = await import('@/api')
    vi.mocked(updateField).mockResolvedValue({
      message: '已保存',
      state: {} as any,
    })
    await editorStore.saveFieldEdit('settings_md_content', '修仙世界，灵气为尊')
    expect(updateField).toHaveBeenCalledWith('settings_md_content', '修仙世界，灵气为尊')
  })

  it('chapter generation → save new chapter', async () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    chatStore.addUserMessage('续写下一章')
    chatStore.streamingContent = ''
    editorStore.startGeneration()

    const events: SseEvent[] = [
      { type: 'generate_start', target: 'chapter_new' },
      { type: 'chapter_title', title: '风起云涌' },
      { type: 'generate_token', target: 'chapter_new', token: '夜色降临...' },
      { type: 'field_content', target: 'chapter_1', content: '夜色降临...' },
      { type: 'generate_done', target: 'chapter_1', title: '风起云涌' },
      { type: 'task_complete', summary: '章节已生成' },
      { type: 'done' },
    ]

    for (const evt of events) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    if (chatStore.streamingContent) {
      chatStore.addAgentMessage(chatStore.streamingContent)
    }
    chatStore.streamingContent = ''
    editorStore.stopGeneration()

    // 验证编辑器切换到 chapter_1（后端已落盘，pending 在 generate_done 后清空）
    expect(editorStore.editingField).toBe('chapter_1')
    expect(editorStore.streamingChapterContent).toBe('夜色降临...')

    // 模拟保存新章节
    const { addChapter } = await import('@/api')
    vi.mocked(addChapter).mockResolvedValue({
      message: '已添加',
      chapter: { idx: 1, title: '风起云涌', is_written: true },
      state: {} as any,
    })
    await editorStore.saveNewChapter('风起云涌', '夜色降临...')
    expect(addChapter).toHaveBeenCalledWith('风起云涌', '夜色降临...')
  })
})

describe('E2E: Multiple field updates in one session', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('generate settings then generate characters sequentially', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    // 第一轮：生成设定
    editorStore.editingField = 'settings_md_content'
    editorStore.startGeneration()

    const events1: SseEvent[] = [
      { type: 'generate_start', target: 'settings_md_content' },
      { type: 'generate_token', target: 'settings_md_content', token: '修仙世界' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'settings_md_content', content: '修仙世界' },
      { type: 'task_complete', summary: '设定完成' },
      { type: 'done' },
    ]

    for (const evt of events1) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    expect(editorStore.fieldValues.settings_md_content).toBe('修仙世界')
    editorStore.stopGeneration()

    // 第二轮：生成角色
    chatStore.streamingContent = ''
    editorStore.startGeneration()

    const events2: SseEvent[] = [
      { type: 'generate_start', target: 'characters_md_content' },
      { type: 'generate_token', target: 'characters_md_content', token: '李逍遥' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'characters_md_content', content: '李逍遥：主角' },
      { type: 'task_complete', summary: '角色完成' },
      { type: 'done' },
    ]

    for (const evt of events2) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    expect(editorStore.fieldValues.characters_md_content).toBe('李逍遥：主角')
    expect(editorStore.editingField).toBe('characters_md_content')

    // 设定内容不受影响
    expect(editorStore.fieldValues.settings_md_content).toBe('修仙世界')

    editorStore.stopGeneration()
  })
})

describe('E2E: Interrupt/Resume flow', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('interrupt event received, then resume with user choice', () => {
    const chatStore = useChatStore()
    const editorStore = useEditorStore()

    chatStore.addUserMessage('重新生成大纲')
    chatStore.streamingContent = ''
    editorStore.startGeneration()

    // 模拟 interrupt 事件
    const events: SseEvent[] = [
      { type: 'token', token: '需要确认...' },
      { type: 'interrupt', interrupt: { message: '是否重读全部章节？' } },
    ]

    for (const evt of events) {
      if (evt.type === 'interrupt') {
        // interrupt 由 ChatPanel.onInterrupt 处理，此处只验证事件格式
        expect(evt.interrupt).toBeDefined()
        expect(evt.interrupt!.message).toBe('是否重读全部章节？')
      } else {
        makeHandleEvent(chatStore, editorStore)(evt)
      }
    }

    expect(chatStore.streamingContent).toContain('需要确认')

    // 模拟用户选择继续（resume）
    // 实际由 ChatPanel 的 handleInterrupt 处理
    // 这里验证 resume 后的事件流
    const resumeEvents: SseEvent[] = [
      { type: 'generate_start', target: 'outline_future_md_content' },
      { type: 'generate_token', target: 'outline_future_md_content', token: '新大纲' },
      { type: 'generate_done' },
      { type: 'field_content', target: 'outline_future_md_content', content: '新大纲内容' },
      { type: 'task_complete', summary: '大纲已生成' },
      { type: 'done' },
    ]

    chatStore.streamingContent = ''
    for (const evt of resumeEvents) {
      makeHandleEvent(chatStore, editorStore)(evt)
    }

    expect(editorStore.fieldValues.outline_future_md_content).toBe('新大纲内容')
    editorStore.stopGeneration()
  })
})

describe('E2E: ChatPanel message ordering and display', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('multiple rounds maintain correct message order', () => {
    const chatStore = useChatStore()

    // 第一轮
    chatStore.addUserMessage('你好')
    chatStore.addAgentMessage('你好！我是墨灵。')

    // 第二轮
    chatStore.addUserMessage('生成设定')
    chatStore.addAgentMessage('设定已生成', '需要生成设定')

    // 第三轮
    chatStore.addUserMessage('续写')
    chatStore.addAgentMessage('章节已续写')

    expect(chatStore.messages.length).toBe(6)
    const roles = chatStore.messages.map(m => m.role)
    expect(roles).toEqual(['user', 'assistant', 'user', 'assistant', 'user', 'assistant'])

    // 只有第二轮有 thinking
    expect(chatStore.messages[1].thinking).toBeUndefined()
    expect(chatStore.messages[3].thinking).toBe('需要生成设定')
    expect(chatStore.messages[5].thinking).toBeUndefined()
  })

  it('clear chat resets all state', () => {
    const chatStore = useChatStore()

    chatStore.addUserMessage('你好')
    chatStore.addAgentMessage('回复')
    chatStore.streamingContent = '流式内容'
    chatStore.showThinking = true
    chatStore.reasoningContent = '思考'

    chatStore.clearMessages()

    expect(chatStore.messages).toEqual([])
    expect(chatStore.streamingContent).toBe('')
    expect(chatStore.showThinking).toBe(false)
    expect(chatStore.reasoningContent).toBe('')
  })
})
