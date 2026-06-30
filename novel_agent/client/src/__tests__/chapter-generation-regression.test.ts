/**
 * 续写下一章 / 生成期间切页 — 回归测试
 *
 * 覆盖此前修复的问题：
 * - chapter_title SSE 需经 createSseHandler.onChapterTitle 更新 UI 标题
 * - generatingStreamContent 与浏览页内容隔离（pinView）
 * - field_content 将 generatingTarget 从 chapter_new 迁移到 chapter_N
 * - generate_start / field_content 在 viewPinned 时不劫持 editingField
 * - onFieldChanged 续写中回到 chapter_new 不清空缓冲
 * - getCurrentContent 在生成目标页读取 generatingStreamContent
 * - startGeneration 清空 pendingChapterTitle
 * - continue_writing 事件顺序：chapter_title → generate_start → … → field_content → generate_done
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useEditorStore, useChatStore } from '@/stores'
import { createSseHandler } from '@/composables/useSseHandler'

vi.mock('@/api', () => ({
  getState: vi.fn().mockResolvedValue({
    current_book_name: '测试',
    has_outline: true,
    meta: { title: '测试', total_chapters: 1 },
    outline: { title: '测试', chapters: [] },
    chapters: [],
    messages: [],
  }),
}))

/** 镜像 EditorPage.getCurrentContent（pages/EditorPage.vue） */
function getCurrentContent(
  store: ReturnType<typeof useEditorStore>,
  titleValue = '',
): string {
  const field = store.editingField
  if (!field) return ''
  if (store.isGenerating && field === store.generatingTarget) {
    return store.generatingStreamContent
  }
  if (field === 'chapter_new' || store.isChapterField(field)) {
    return store.streamingChapterContent
  }
  if (field === 'title') return titleValue
  return store.streamingFieldContent
}

/** 镜像 EditorPage.onFieldChanged 中 chapter_new 分支 */
function simulateOnFieldChangedChapterNew(
  store: ReturnType<typeof useEditorStore>,
  chapterTitle: { value: string },
) {
  if (store.editingField !== 'chapter_new') return
  chapterTitle.value = store.pendingChapterTitle || chapterTitle.value || ''
  const resumingGeneration =
    store.isGenerating && store.generatingTarget === 'chapter_new'
  if (!resumingGeneration) {
    store.streamingChapterContent = ''
  }
}

/** 镜像 EditorPage.isStreamingToField */
function isStreamingToField(store: ReturnType<typeof useEditorStore>): boolean {
  return (
    store.isGenerating
    && !!store.generatingTarget
    && store.editingField === store.generatingTarget
  )
}

/** 镜像 EditorPage.doSaveCurrent 的 chapter_new 自动保存跳过逻辑 */
function shouldSkipAutoSave(field: string, isAuto: boolean): boolean {
  return isAuto && field === 'chapter_new'
}

describe('Chapter generation regressions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  describe('createSseHandler — chapter_title', () => {
    it('sets pendingChapterTitle and invokes onChapterTitle hook', () => {
      const editorStore = useEditorStore()
      const chatStore = useChatStore()
      let uiTitle = ''
      const handleEvent = createSseHandler(chatStore, editorStore, {
        onChapterTitle: (title) => { uiTitle = title },
      })

      handleEvent({ type: 'chapter_title', title: '正文卷 第6章 查账寻踪', chapter_num: 6 })

      expect(editorStore.pendingChapterTitle).toBe('正文卷 第6章 查账寻踪')
      expect(uiTitle).toBe('正文卷 第6章 查账寻踪')
    })

    it('sets pendingChapterTitle even without onChapterTitle hook', () => {
      const editorStore = useEditorStore()
      const chatStore = useChatStore()
      const handleEvent = createSseHandler(chatStore, editorStore)

      handleEvent({ type: 'chapter_title', title: '正文卷 第2章 风起云涌', chapter_num: 2 })

      expect(editorStore.pendingChapterTitle).toBe('正文卷 第2章 风起云涌')
    })
  })

  describe('continue_writing SSE sequence', () => {
    it('migrates generatingTarget from chapter_new to chapter_N on field_content', () => {
      const editorStore = useEditorStore()
      const chatStore = useChatStore()
      editorStore.startGeneration()
      const handleEvent = createSseHandler(chatStore, editorStore)

      handleEvent({ type: 'chapter_title', title: '正文卷 第6章 查账寻踪', chapter_num: 6 })
      handleEvent({ type: 'generate_start', target: 'chapter_new' })
      handleEvent({ type: 'generate_token', target: 'chapter_new', token: '第一段' })
      handleEvent({ type: 'generate_token', target: 'chapter_new', token: '第二段' })
      handleEvent({
        type: 'field_content',
        target: 'chapter_6',
        content: '第一段第二段',
      })

      expect(editorStore.generatingTarget).toBe('chapter_6')
      expect(editorStore.generatingStreamContent).toBe('第一段第二段')

      handleEvent({ type: 'generate_done', target: 'chapter_6', title: '正文卷 第6章 查账寻踪' })

      expect(editorStore.isGenerating).toBe(false)
      expect(editorStore.generatingTarget).toBe('')
    })

    it('streams tokens into generatingStreamContent on chapter_new target', () => {
      const editorStore = useEditorStore()
      const chatStore = useChatStore()
      const handleEvent = createSseHandler(chatStore, editorStore)

      editorStore.startGeneration()
      handleEvent({ type: 'generate_start', target: 'chapter_new' })
      handleEvent({ type: 'generate_token', target: 'chapter_new', token: '流式正文' })

      expect(editorStore.generatingTarget).toBe('chapter_new')
      expect(editorStore.generatingStreamContent).toBe('流式正文')
    })
  })

  describe('view pinning during generation', () => {
    it('generate_start does not switch editingField when viewPinned', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.editingField = 'chapter_1'
      store.streamingChapterContent = '第一章已有正文'
      store.pinView('chapter_1')

      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })

      expect(store.editingField).toBe('chapter_1')
      expect(store.generatingTarget).toBe('chapter_new')
      expect(store.streamingChapterContent).toBe('第一章已有正文')
    })

    it('field_content does not hijack editingField when viewPinned', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.streamingFieldContent = '设定原文'
      store.pinView('settings_md_content')

      store.handleGenerateEvent({
        type: 'field_content',
        target: 'chapter_6',
        content: '第六章定稿',
      })

      expect(store.editingField).toBe('settings_md_content')
      expect(store.generatingTarget).toBe('chapter_6')
      expect(store.generatingStreamContent).toBe('第六章定稿')
      expect(store.streamingFieldContent).toBe('设定原文')
    })

    it('isStreamingToField is false when viewing a pinned non-target page', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.pinView('settings_md_content')

      expect(isStreamingToField(store)).toBe(false)
    })

    it('isStreamingToField is true when viewing the generating target', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })

      expect(isStreamingToField(store)).toBe(true)
    })
  })

  describe('generatingStreamContent isolation', () => {
    it('getCurrentContent reads generatingStreamContent on generating target page', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.handleGenerateEvent({ type: 'generate_token', target: 'chapter_new', token: '新章正文' })
      store.streamingChapterContent = '旧缓冲不应显示'

      expect(getCurrentContent(store)).toBe('新章正文')
    })

    it('getCurrentContent reads streamingChapterContent when viewing another chapter while generating', () => {
      const store = useEditorStore()
      store.streamingChapterContent = '第一章正文'
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.handleGenerateEvent({ type: 'generate_token', target: 'chapter_new', token: '新章' })
      store.pinView('chapter_1')

      expect(getCurrentContent(store)).toBe('第一章正文')
      expect(store.generatingStreamContent).toBe('新章')
    })

    it('onFieldChanged does not clear buffer when resuming chapter_new during generation', () => {
      const store = useEditorStore()
      const chapterTitle = { value: '' }
      store.streamingChapterContent = '续写中的旧缓冲'
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.handleGenerateEvent({ type: 'generate_token', target: 'chapter_new', token: '流式新内容' })
      store.pendingChapterTitle = '正文卷 第6章 查账寻踪'
      store.pinView('settings_md_content')
      store.pinView('chapter_new')

      simulateOnFieldChangedChapterNew(store, chapterTitle)

      expect(store.streamingChapterContent).toBe('续写中的旧缓冲')
      expect(getCurrentContent(store)).toBe('流式新内容')
      expect(chapterTitle.value).toBe('正文卷 第6章 查账寻踪')
    })

    it('onFieldChanged clears buffer when opening chapter_new outside generation', () => {
      const store = useEditorStore()
      const chapterTitle = { value: '旧标题' }
      store.streamingChapterContent = '旧正文'
      store.editingField = 'chapter_new'

      simulateOnFieldChangedChapterNew(store, chapterTitle)

      expect(store.streamingChapterContent).toBe('')
    })
  })

  describe('startGeneration session reset', () => {
    it('clears pendingChapterTitle and generatingStreamContent', () => {
      const store = useEditorStore()
      store.pendingChapterTitle = '旧 pending 标题'
      store.generatingStreamContent = '旧流式内容'

      store.startGeneration()

      expect(store.pendingChapterTitle).toBe('')
      expect(store.generatingStreamContent).toBe('')
    })
  })

  describe('auto-save guard for continue_writing', () => {
    it('skips auto-save on chapter_new because backend already persisted', () => {
      expect(shouldSkipAutoSave('chapter_new', true)).toBe(true)
      expect(shouldSkipAutoSave('chapter_new', false)).toBe(false)
      expect(shouldSkipAutoSave('chapter_6', true)).toBe(false)
    })
  })
})
