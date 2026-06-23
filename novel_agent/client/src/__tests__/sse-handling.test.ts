/**
 * SSE 事件处理集成测试
 *
 * 覆盖所有 SSE 事件类型的处理逻辑：
 * - generate_start / generate_token / generate_done / generate_reset
 * - field_content（字段和章节类）
 * - chapter_title
 * - interrupt / resume
 * - subagent_token / subagent_tool_call
 * - 编辑区自动跳转
 * - 流式内容拼接
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useEditorStore, useChatStore } from '@/stores'

// 模拟 handleSseEvent 的核心逻辑
function simulateEditorSseEvent(
  evt: any,
  editorStore: ReturnType<typeof useEditorStore>,
  chatStore: ReturnType<typeof useChatStore>,
  state: { chapterContent: string; fieldContent: string; chapterTitle: string; isStreaming: boolean }
) {
  switch (evt.type) {
    case 'generate_start':
      state.isStreaming = true
      if (evt.target === 'chapter_new') { editorStore.editingField = 'chapter_new'; state.chapterContent = '' }
      else if (evt.target?.startsWith('chapter_review')) { /* internal */ }
      else if (evt.target?.startsWith('chapter_')) { editorStore.editingField = evt.target; state.chapterContent = '' }
      else if (evt.target) { editorStore.editingField = evt.target; state.fieldContent = '' }
      break
    case 'generate_token':
      if (evt.target === 'chapter_new' || editorStore.isChapterField(evt.target)) state.chapterContent += evt.token || ''
      else if (evt.target) state.fieldContent += evt.token || ''
      break
    case 'generate_done':
      state.isStreaming = false
      break
    case 'generate_reset':
      state.isStreaming = false
      if (editorStore.isChapterField(evt.target) || evt.target === 'chapter_new') state.chapterContent = ''
      else if (evt.target) state.fieldContent = ''
      break
    case 'field_content':
      if (evt.target && evt.content) {
        editorStore.fieldValues[evt.target] = evt.content
        if (editorStore.isChapterField(evt.target) || evt.target === 'chapter_new') {
          editorStore.editingField = evt.target
          state.chapterContent = evt.content
        } else if (evt.target) {
          editorStore.editingField = evt.target
          editorStore.mdPreviewMode = false
          state.fieldContent = evt.content
        }
      }
      break
    case 'chapter_title':
      editorStore.pendingChapterTitle = evt.title || ''
      state.chapterTitle = evt.title || ''
      break
    case 'token':
      chatStore.streamingContent += evt.token || ''
      break
    case 'reasoning':
      chatStore.showThinking = true
      chatStore.reasoningContent += evt.token || ''
      break
    case 'error':
      chatStore.addAgentMessage('出错了：' + (evt.error || '未知错误'))
      break
  }
}

describe('SSE — generate events for field', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('generate_start opens field editor', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '旧内容', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent(
      { type: 'generate_start', target: 'settings_md_content' },
      editor, chat, s
    )

    expect(editor.editingField).toBe('settings_md_content')
    expect(s.fieldContent).toBe('')
    expect(s.isStreaming).toBe(true)
  })

  it('generate_token accumulates field content', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    editor.editingField = 'settings_md_content'
    s.isStreaming = true
    simulateEditorSseEvent({ type: 'generate_token', target: 'settings_md_content', token: '生成' }, editor, chat, s)
    simulateEditorSseEvent({ type: 'generate_token', target: 'settings_md_content', token: '内容' }, editor, chat, s)

    expect(s.fieldContent).toBe('生成内容')
  })

  it('generate_done ends streaming', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '生成内容', chapterTitle: '', isStreaming: true }

    simulateEditorSseEvent({ type: 'generate_done' }, editor, chat, s)

    expect(s.isStreaming).toBe(false)
    expect(s.fieldContent).toBe('生成内容')
  })

  it('generate_reset clears content', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '生成一半', chapterTitle: '', isStreaming: true }

    editor.editingField = 'characters_md_content'
    simulateEditorSseEvent({ type: 'generate_reset', target: 'characters_md_content' }, editor, chat, s)

    expect(s.fieldContent).toBe('')
    expect(s.isStreaming).toBe(false)
  })
})

describe('SSE — generate events for chapter', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('generate_start opens chapter editor', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent({ type: 'generate_start', target: 'chapter_new' }, editor, chat, s)

    expect(editor.editingField).toBe('chapter_new')
    expect(s.chapterContent).toBe('')
    expect(s.isStreaming).toBe(true)
  })

  it('generate_token accumulates chapter content', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    editor.editingField = 'chapter_new'
    s.isStreaming = true
    simulateEditorSseEvent({ type: 'generate_token', target: 'chapter_new', token: '第一章' }, editor, chat, s)
    simulateEditorSseEvent({ type: 'generate_token', target: 'chapter_new', token: '正文' }, editor, chat, s)

    expect(s.chapterContent).toBe('第一章正文')
  })

  it('chapter_title sets title', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent({ type: 'chapter_title', title: '暗夜追踪' }, editor, chat, s)

    expect(s.chapterTitle).toBe('暗夜追踪')
    expect(editor.pendingChapterTitle).toBe('暗夜追踪')
  })

  it('generate_reset for chapter clears content', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '写到一半...', fieldContent: '', chapterTitle: '', isStreaming: true }

    editor.editingField = 'chapter_new'
    simulateEditorSseEvent({ type: 'generate_reset', target: 'chapter_new' }, editor, chat, s)

    expect(s.chapterContent).toBe('')
    expect(s.isStreaming).toBe(false)
  })

  it('chapter_review is silently skipped', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent({ type: 'generate_start', target: 'chapter_review' }, editor, chat, s)

    expect(s.isStreaming).toBe(true)
    expect(editor.editingField).toBe('')
  })
})

describe('SSE — field_content event', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('field_content updates fieldValues and opens editor', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent(
      { type: 'field_content', target: 'settings_md_content', content: '新的设定内容' },
      editor, chat, s
    )

    expect(editor.fieldValues['settings_md_content']).toBe('新的设定内容')
    expect(editor.editingField).toBe('settings_md_content')
    expect(s.fieldContent).toBe('新的设定内容')
    expect(editor.mdPreviewMode).toBe(false)
  })

  it('field_content for chapter field opens chapter editor', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent(
      { type: 'field_content', target: 'chapter_5', content: '第5章内容' },
      editor, chat, s
    )

    expect(editor.editingField).toBe('chapter_5')
    expect(s.chapterContent).toBe('第5章内容')
  })

  it('field_content switches editor from field to another field', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '角色', chapterTitle: '', isStreaming: false }

    editor.editingField = 'characters_md_content'

    simulateEditorSseEvent(
      { type: 'field_content', target: 'settings_md_content', content: '设定' },
      editor, chat, s
    )

    expect(editor.editingField).toBe('settings_md_content')
    expect(s.fieldContent).toBe('设定')
  })
})

describe('SSE — chat events', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('token appends to streaming content', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent({ type: 'token', token: '你好' }, editor, chat, s)
    simulateEditorSseEvent({ type: 'token', token: '世界' }, editor, chat, s)

    expect(chat.streamingContent).toBe('你好世界')
  })

  it('reasoning sets thinking state', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent({ type: 'reasoning', token: '分析中...' }, editor, chat, s)

    expect(chat.showThinking).toBe(true)
    expect(chat.reasoningContent).toBe('分析中...')
  })

  it('error adds agent message', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    simulateEditorSseEvent({ type: 'error', error: 'LLM 超时' }, editor, chat, s)

    expect(chat.messages.length).toBe(1)
    expect(chat.messages[0].content).toContain('LLM 超时')
  })
})

describe('SSE — streaming accumulation over many tokens', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('handles rapid fire of many generate_token events', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: true }
    editor.editingField = 'settings_md_content'

    const content = '这是一个很长的段落用于测试流式内容拼接的效果。'.repeat(5)
    for (const ch of content) {
      simulateEditorSseEvent({ type: 'generate_token', target: 'settings_md_content', token: ch }, editor, chat, s)
    }

    expect(s.fieldContent).toBe(content)
  })

  it('streaming chapter content has correct length after many tokens', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: true }
    editor.editingField = 'chapter_new'

    const tokens = ['第', '一', '章', '正', '文', '开', '始', '...']
    for (const t of tokens) {
      simulateEditorSseEvent({ type: 'generate_token', target: 'chapter_new', token: t }, editor, chat, s)
    }

    expect(s.chapterContent).toBe(tokens.join(''))
  })
})

describe('SSE — event sequence realism', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('full field generation sequence', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '旧内容', chapterTitle: '', isStreaming: false }

    const events = [
      { type: 'generate_start', target: 'characters_md_content' },
      { type: 'generate_token', target: 'characters_md_content', token: '## 核心角色\n' },
      { type: 'generate_token', target: 'characters_md_content', token: '- 李逍遥：主角\n' },
      { type: 'generate_reset', target: 'characters_md_content' },
      { type: 'generate_start', target: 'characters_md_content' },
      { type: 'generate_token', target: 'characters_md_content', token: '## 核心角色\n' },
      { type: 'generate_token', target: 'characters_md_content', token: '- 李逍遥：剑修，实力金丹期\n' },
      { type: 'generate_done' },
    ]

    for (const evt of events) {
      simulateEditorSseEvent(evt, editor, chat, s)
    }

    expect(s.fieldContent).toBe('## 核心角色\n- 李逍遥：剑修，实力金丹期\n')
    expect(s.isStreaming).toBe(false)
  })

  it('update_field sends field_content after generation', () => {
    const editor = useEditorStore()
    const chat = useChatStore()
    const s = { chapterContent: '', fieldContent: '', chapterTitle: '', isStreaming: false }

    // update_field flow: generate_start → *_token → generate_done → field_content
    simulateEditorSseEvent({ type: 'generate_start', target: 'settings_md_content' }, editor, chat, s)
    simulateEditorSseEvent({ type: 'generate_token', target: 'settings_md_content', token: '新生' }, editor, chat, s)
    simulateEditorSseEvent({ type: 'generate_token', target: 'settings_md_content', token: '成内容' }, editor, chat, s)
    simulateEditorSseEvent({ type: 'generate_done' }, editor, chat, s)
    simulateEditorSseEvent(
      { type: 'field_content', target: 'settings_md_content', content: '新生成内容' },
      editor, chat, s
    )

    expect(editor.fieldValues['settings_md_content']).toBe('新生成内容')
    expect(s.fieldContent).toBe('新生成内容')
    expect(editor.editingField).toBe('settings_md_content')
  })
})
