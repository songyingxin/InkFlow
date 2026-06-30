/**
 * Pinia Store 测试
 *
 * 测试前端 Store 的状态管理逻辑：
 * - useBookStore: 书籍列表管理
 * - useEditorStore: 编辑器状态、章节管理、字段编辑、历史记录
 * - useChatStore: 对话消息管理
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useBookStore, useEditorStore, useChatStore } from '@/stores'

describe('useBookStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initial state', () => {
    const store = useBookStore()
    expect(store.books).toEqual([])
    expect(store.loading).toBe(false)
    expect(store.error).toBe('')
  })

  it('fetchBooks sets loading state', async () => {
    const store = useBookStore()
    const mockFetch = vi.fn().mockResolvedValue({ books: [{ name: 'test', title: '测试', total_chapters: 0 }] })
    vi.spyOn(await import('@/api'), 'listBooks').mockImplementation(mockFetch)

    const promise = store.fetchBooks()
    expect(store.loading).toBe(true)
    await promise
    expect(store.loading).toBe(false)
    expect(store.books.length).toBe(1)
  })

  it('fetchBooks handles error', async () => {
    const store = useBookStore()
    vi.spyOn(await import('@/api'), 'listBooks').mockRejectedValue(new Error('网络错误'))

    await store.fetchBooks()
    expect(store.error).toBe('网络错误')
    expect(store.loading).toBe(false)
  })
})

describe('useEditorStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initial state', () => {
    const store = useEditorStore()
    expect(store.currentState).toBeNull()
    expect(store.activeChapterIdx).toBeNull()
    expect(store.editingField).toBe('')
    expect(store.sidebarVisible).toBe(true)
    expect(store.mdPreviewMode).toBe(false)
    expect(store.isDirty).toBe(false)
    expect(store.isGenerating).toBe(false)
    expect(store.fieldValues).toEqual({})
  })

  describe('isChapterField', () => {
    it('returns true for chapter fields', () => {
      const store = useEditorStore()
      expect(store.isChapterField('chapter_1')).toBe(true)
      expect(store.isChapterField('chapter_10')).toBe(true)
    })

    it('returns false for non-chapter fields', () => {
      const store = useEditorStore()
      expect(store.isChapterField('settings_md_content')).toBe(false)
      expect(store.isChapterField('title')).toBe(false)
      expect(store.isChapterField('')).toBeFalsy()
    })
  })

  describe('isNewChapter', () => {
    it('returns true for chapter_new', () => {
      const store = useEditorStore()
      store.editingField = 'chapter_new'
      expect(store.isNewChapter()).toBe(true)
    })

    it('returns false for other fields', () => {
      const store = useEditorStore()
      store.editingField = 'chapter_1'
      expect(store.isNewChapter()).toBe(false)
    })
  })

  describe('getChapterIdx', () => {
    it('extracts chapter index', () => {
      const store = useEditorStore()
      store.editingField = 'chapter_5'
      expect(store.getChapterIdx()).toBe(5)
    })

    it('returns null for non-chapter fields', () => {
      const store = useEditorStore()
      store.editingField = 'settings_md_content'
      expect(store.getChapterIdx()).toBeNull()
    })
  })

  describe('cleanPlaceholder', () => {
    it('returns empty for placeholder values', () => {
      const store = useEditorStore()
      expect(store.cleanPlaceholder('暂无设定')).toBe('')
      expect(store.cleanPlaceholder('暂无角色')).toBe('')
      expect(store.cleanPlaceholder('暂无大纲')).toBe('')
      expect(store.cleanPlaceholder('暂无关系图谱')).toBe('')
      expect(store.cleanPlaceholder('暂无伏笔')).toBe('')
    })

    it('returns original value for non-placeholder', () => {
      const store = useEditorStore()
      expect(store.cleanPlaceholder('真实内容')).toBe('真实内容')
    })

    it('returns empty for empty string', () => {
      const store = useEditorStore()
      expect(store.cleanPlaceholder('')).toBe('')
    })
  })

  describe('dirty state', () => {
    it('markDirty sets isDirty', () => {
      const store = useEditorStore()
      store.markDirty()
      expect(store.isDirty).toBe(true)
    })

    it('resetDirty clears isDirty and hasUnsavedGenerated', () => {
      const store = useEditorStore()
      store.markDirty()
      store.hasUnsavedGenerated = true
      store.resetDirty()
      expect(store.isDirty).toBe(false)
      expect(store.hasUnsavedGenerated).toBe(false)
    })
  })

  describe('generation control', () => {
    it('startGeneration sets isGenerating and creates AbortController', () => {
      const store = useEditorStore()
      store.startGeneration()
      expect(store.isGenerating).toBe(true)
      expect(store.abortController).toBeInstanceOf(AbortController)
    })

    it('stopGeneration clears state', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.stopGeneration()
      expect(store.isGenerating).toBe(false)
      expect(store.abortController).toBeNull()
    })

    it('pinView keeps sidebar field visible during generation', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.handleGenerateEvent({ type: 'generate_token', target: 'chapter_new', token: '流式' })
      store.pinView('settings_md_content')

      store.handleGenerateEvent({
        type: 'field_content',
        target: 'chapter_6',
        content: '第六章正文',
      })

      expect(store.editingField).toBe('settings_md_content')
      expect(store.generatingStreamContent).toBe('第六章正文')
      expect(store.generatingTarget).toBe('chapter_6')
      expect(store.streamingFieldContent).not.toBe('第六章正文')
    })

    it('generate_token only writes to generatingStreamContent', () => {
      const store = useEditorStore()
      store.editingField = 'settings_md_content'
      store.streamingFieldContent = '设定原文'
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.pinView('settings_md_content')
      store.handleGenerateEvent({ type: 'generate_token', target: 'chapter_new', token: '新章' })

      expect(store.generatingStreamContent).toBe('新章')
      expect(store.streamingFieldContent).toBe('设定原文')
    })

    it('pinView on generating target resumes auto-follow', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.pinView('settings_md_content')
      expect(store.viewPinned).toBe(true)

      store.pinView('chapter_new')
      expect(store.viewPinned).toBe(false)
      expect(store.editingField).toBe('chapter_new')
    })

    it('generate_start clears generatingStreamContent but not browsing chapter buffer when pinned', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.streamingChapterContent = '第一章正文'
      store.pinView('chapter_1')
      store.generatingStreamContent = '残留'

      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.handleGenerateEvent({ type: 'generate_token', target: 'chapter_new', token: '新章' })

      expect(store.streamingChapterContent).toBe('第一章正文')
      expect(store.generatingStreamContent).toBe('新章')
      expect(store.editingField).toBe('chapter_1')
    })

    it('field_content updates generatingTarget from chapter_new to saved chapter', () => {
      const store = useEditorStore()
      store.startGeneration()
      store.handleGenerateEvent({ type: 'generate_start', target: 'chapter_new' })
      store.handleGenerateEvent({ type: 'generate_token', target: 'chapter_new', token: '正文' })

      store.handleGenerateEvent({
        type: 'field_content',
        target: 'chapter_6',
        content: '正文',
      })

      expect(store.generatingTarget).toBe('chapter_6')
      expect(store.generatingStreamContent).toBe('正文')
      expect(store.streamingChapterContent).toBe('正文')
    })

    it('startGeneration clears pendingChapterTitle', () => {
      const store = useEditorStore()
      store.pendingChapterTitle = '正文卷 第6章 查账寻踪'

      store.startGeneration()

      expect(store.pendingChapterTitle).toBe('')
    })
  })

  describe('content history', () => {
    it('pushContentSnapshot adds entry', () => {
      const store = useEditorStore()
      store.pushContentSnapshot('生成')
      expect(store.contentHistory.length).toBe(1)
      expect(store.historyIndex).toBe(0)
    })

    it('canUndoGeneration returns false initially', () => {
      const store = useEditorStore()
      expect(store.canUndoGeneration()).toBe(false)
    })

    it('canUndoGeneration returns true after push', () => {
      const store = useEditorStore()
      store.editingField = 'settings_md_content'
      store.pushContentSnapshot('生成')
      expect(store.canUndoGeneration()).toBe(false)

      store.pushContentSnapshot('再次生成')
      expect(store.canUndoGeneration()).toBe(true)
    })

    it('undoGeneration returns null when nothing to undo', () => {
      const store = useEditorStore()
      expect(store.undoGeneration()).toBeNull()
    })

    it('redoGeneration returns null when nothing to redo', () => {
      const store = useEditorStore()
      expect(store.redoGeneration()).toBeNull()
    })

    it('history is capped at MAX_HISTORY', () => {
      const store = useEditorStore()
      for (let i = 0; i < 25; i++) {
        store.pushContentSnapshot(`生成${i}`)
      }
      expect(store.contentHistory.length).toBeLessThanOrEqual(20)
    })
  })

  describe('sidebar', () => {
    it('toggleSidebar toggles visibility', () => {
      const store = useEditorStore()
      expect(store.sidebarVisible).toBe(true)
      store.toggleSidebar()
      expect(store.sidebarVisible).toBe(false)
      store.toggleSidebar()
      expect(store.sidebarVisible).toBe(true)
    })
  })

  describe('computed properties', () => {
    it('chapters returns empty array when no state', () => {
      const store = useEditorStore()
      expect(store.chapters).toEqual([])
    })

    it('currentBookName returns empty string when no state', () => {
      const store = useEditorStore()
      expect(store.currentBookName).toBe('')
    })

    it('hasOutline returns false when no state', () => {
      const store = useEditorStore()
      expect(store.hasOutline).toBe(false)
    })
  })
})

describe('useChatStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('initial state', () => {
    const store = useChatStore()
    expect(store.messages).toEqual([])
    expect(store.streamingContent).toBe('')
    expect(store.reasoningContent).toBe('')
    expect(store.showThinking).toBe(false)
    expect(store.thinkingCollapsed).toBe(false)
  })

  describe('addUserMessage', () => {
    it('adds user message', () => {
      const store = useChatStore()
      store.addUserMessage('你好')
      expect(store.messages.length).toBe(1)
      expect(store.messages[0].role).toBe('user')
      expect(store.messages[0].content).toBe('你好')
    })
  })

  describe('addAgentMessage', () => {
    it('adds agent message without thinking', () => {
      const store = useChatStore()
      store.addAgentMessage('你好！')
      expect(store.messages.length).toBe(1)
      expect(store.messages[0].role).toBe('assistant')
      expect(store.messages[0].content).toBe('你好！')
      expect(store.messages[0].thinking).toBeUndefined()
    })

    it('adds agent message with thinking', () => {
      const store = useChatStore()
      store.addAgentMessage('回复', '思考过程')
      expect(store.messages[0].thinking).toBe('思考过程')
    })
  })

  describe('clearMessages', () => {
    it('clears all messages and state', () => {
      const store = useChatStore()
      store.addUserMessage('你好')
      store.streamingContent = '流式内容'
      store.reasoningContent = '推理内容'
      store.showThinking = true
      store.clearMessages()
      expect(store.messages).toEqual([])
      expect(store.streamingContent).toBe('')
      expect(store.reasoningContent).toBe('')
      expect(store.showThinking).toBe(false)
    })
  })

  it('maintains message order', () => {
    const store = useChatStore()
    store.addUserMessage('第一条')
    store.addAgentMessage('回复一')
    store.addUserMessage('第二条')
    expect(store.messages.length).toBe(3)
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[1].role).toBe('assistant')
    expect(store.messages[2].role).toBe('user')
  })

  describe('thinkingCollapsed', () => {
    it('defaults to false', () => {
      const store = useChatStore()
      expect(store.thinkingCollapsed).toBe(false)
    })
  })
})

describe('useEditorStore - fetchState', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('fetchState populates fieldValues', async () => {
    const store = useEditorStore()
    const mockState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 1 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
      settings_md_content: '设定内容',
      characters_md_content: '角色内容',
    }
    vi.spyOn(await import('@/api'), 'getState').mockResolvedValue(mockState as any)

    await store.fetchState()
    expect(store.currentState).toEqual(mockState)
    expect(store.fieldValues.title).toBe('测试小说')
    expect(store.fieldValues.settings_md_content).toBe('设定内容')
    expect(store.fieldValues.characters_md_content).toBe('角色内容')
  })
})

describe('useEditorStore - contentHistory edge cases', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('undoGeneration restores previous snapshot', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    store.fieldValues.settings_md_content = '版本1'
    store.pushContentSnapshot('初始')
    store.fieldValues.settings_md_content = '版本2'
    store.pushContentSnapshot('生成')
    const snapshot = store.undoGeneration()
    expect(snapshot).not.toBeNull()
    expect(snapshot!.content).toBe('版本1')
  })

  it('redoGeneration restores next snapshot', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    store.fieldValues.settings_md_content = '版本1'
    store.pushContentSnapshot('初始')
    store.fieldValues.settings_md_content = '版本2'
    store.pushContentSnapshot('生成')
    store.undoGeneration()
    const snapshot = store.redoGeneration()
    expect(snapshot).not.toBeNull()
    expect(snapshot!.content).toBe('版本2')
  })

  it('canRedoGeneration returns false when at latest', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    store.pushContentSnapshot('初始')
    expect(store.canRedoGeneration()).toBe(false)
  })
})

describe('useBookStore - createBook', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('createBook calls API and returns data', async () => {
    const store = useBookStore()
    const mockResponse = { message: 'ok', book: { name: 'test', title: '测试', total_chapters: 0 }, state: {} }
    vi.spyOn(await import('@/api'), 'createBook').mockResolvedValue(mockResponse as any)
    const result = await store.createBook('测试')
    expect(result.message).toBe('ok')
  })

  it('deleteBook updates books list', async () => {
    const store = useBookStore()
    store.books = [
      { name: 'test1', title: '小说1', total_chapters: 0 },
      { name: 'test2', title: '小说2', total_chapters: 0 },
    ]
    const mockResponse = { message: 'ok', books: [{ name: 'test2', title: '小说2', total_chapters: 0 }] }
    vi.spyOn(await import('@/api'), 'deleteBook').mockResolvedValue(mockResponse as any)
    await store.deleteBook('test1')
    expect(store.books.length).toBe(1)
    expect(store.books[0].name).toBe('test2')
  })
})
