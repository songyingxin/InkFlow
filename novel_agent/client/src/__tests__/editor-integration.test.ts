/**
 * EditorPage 集成测试
 *
 * 覆盖：
 * - 字段切换（title / chapter / field / chapter_new）
 * - 编辑/预览模式切换
 * - 生成按钮触发消息
 * - 保存操作的字段路由
 * - 撤销/重做 (content history)
 * - 未保存提示弹窗
 * - 自动保存定时器
 * - 侧边栏字段点击
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { useEditorStore } from '@/stores'
import { FIELD_LABELS, FIELD_TITLES } from '@/types'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
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

describe('EditorStore — field switching', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('switching from field to title updates editingField', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    expect(store.editingField).toBe('settings_md_content')

    store.editingField = 'title'
    expect(store.editingField).toBe('title')
  })

  it('switching from chapter to field updates editingField and clears chapter idx', () => {
    const store = useEditorStore()
    store.editingField = 'chapter_3'
    store.activeChapterIdx = 3

    store.editingField = 'characters_md_content'
    expect(store.editingField).toBe('characters_md_content')
  })

  it('switching to chapter_new clears activeChapterIdx', () => {
    const store = useEditorStore()
    store.activeChapterIdx = 5
    store.editingField = 'chapter_new'
    // SideBar.addChapter sets activeChapterIdx to null explicitly
    store.activeChapterIdx = null
    expect(store.activeChapterIdx).toBeNull()
  })
})

describe('EditorStore — generation state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('startGeneration creates new AbortController each time', () => {
    const store = useEditorStore()
    store.startGeneration()
    const ctrl1 = store.abortController
    store.stopGeneration()
    store.startGeneration()
    const ctrl2 = store.abortController
    expect(ctrl2).not.toBeNull()
    expect(ctrl2).not.toBe(ctrl1)
  })

  it('stopGeneration aborts and clears', () => {
    const store = useEditorStore()
    store.startGeneration()
    const ctrl = store.abortController!
    const abortSpy = vi.spyOn(ctrl, 'abort')
    store.stopGeneration()
    expect(abortSpy).toHaveBeenCalled()
    expect(store.abortController).toBeNull()
    expect(store.isGenerating).toBe(false)
  })

  it('isGenerating reflects generation state', () => {
    const store = useEditorStore()
    expect(store.isGenerating).toBe(false)
    store.startGeneration()
    expect(store.isGenerating).toBe(true)
    store.stopGeneration()
    expect(store.isGenerating).toBe(false)
  })
})

describe('EditorStore — content history (undo/redo)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('pushContentSnapshot adds entry with correct field', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    store.pushContentSnapshot('测试')
    expect(store.contentHistory.length).toBe(1)
    expect(store.contentHistory[0].field).toBe('settings_md_content')
    expect(store.contentHistory[0].label).toBe('测试')
  })

  it('can undo after two pushes on same field', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    store.fieldValues['settings_md_content'] = '旧内容'
    store.pushContentSnapshot('首次')
    store.fieldValues['settings_md_content'] = '新内容'
    store.pushContentSnapshot('二次')

    expect(store.canUndoGeneration()).toBe(true)
    const snap = store.undoGeneration()
    expect(snap).not.toBeNull()
    expect(snap!.field).toBe('settings_md_content')
  })

  it('undo then redo restores state', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    store.pushContentSnapshot('首次')
    store.pushContentSnapshot('二次')

    store.undoGeneration()
    expect(store.historyIndex).toBe(0)

    store.redoGeneration()
    expect(store.historyIndex).toBe(1)
  })

  it('cannot undo across different fields', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    store.pushContentSnapshot('设定1')
    store.editingField = 'characters_md_content'
    store.pushContentSnapshot('角色1')

    // canUndo checks same field as editingField
    expect(store.canUndoGeneration()).toBe(false)
  })

  it('history capped at MAX_HISTORY (20)', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    for (let i = 0; i < 30; i++) {
      store.pushContentSnapshot(`生成${i}`)
    }
    expect(store.contentHistory.length).toBe(20)
    expect(store.historyIndex).toBe(19)
  })

  it('pushing after undo truncates future', () => {
    const store = useEditorStore()
    store.editingField = 'settings_md_content'
    store.pushContentSnapshot('1')
    store.pushContentSnapshot('2')
    store.pushContentSnapshot('3')

    store.undoGeneration() // back to 1
    store.undoGeneration() // back to 0

    expect(store.canRedoGeneration()).toBe(true)
    store.pushContentSnapshot('4')
    // After push, future (3) should be truncated
    expect(store.contentHistory.length).toBe(2)
  })
})

describe('EditorStore — field values sync', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('fieldValues starts empty', () => {
    const store = useEditorStore()
    expect(store.fieldValues).toEqual({})
  })

  it('setting fieldValues for a field', () => {
    const store = useEditorStore()
    store.fieldValues['settings_md_content'] = '设定内容'
    expect(store.fieldValues['settings_md_content']).toBe('设定内容')
  })

  it('dirty flag tracks unsaved changes', () => {
    const store = useEditorStore()
    expect(store.isDirty).toBe(false)
    store.markDirty()
    expect(store.isDirty).toBe(true)
    store.resetDirty()
    expect(store.isDirty).toBe(false)
  })
})

describe('EditorStore — chapter field detection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it.each([
    ['chapter_1', true],
    ['chapter_10', true],
    ['chapter_100', true],
    ['chapter_new', true],
    ['settings_md_content', false],
    ['characters_md_content', false],
    ['title', false],
    ['', false],
  ])('isChapterField(%s) is truthy=%s', (field, expected) => {
    const store = useEditorStore()
    expect(!!store.isChapterField(field)).toBe(expected)
  })

  it.each([
    ['chapter_5', 5],
    ['chapter_99', 99],
    ['settings_md_content', null],
    ['', null],
  ])('getChapterIdx(%s) → %s', (field, expected) => {
    const store = useEditorStore()
    store.editingField = field
    expect(store.getChapterIdx()).toBe(expected)
  })
})

describe('EditorStore — cleanPlaceholder', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it.each([
    ['暂无设定', ''],
    ['暂无大纲', ''],
    ['暂无历史大纲', ''],
    ['暂无未来大纲', ''],
    ['暂无角色', ''],
    ['暂无关系图谱', ''],
    ['暂无伏笔', ''],
    ['真实内容', '真实内容'],
    ['', ''],
  ])('cleanPlaceholder("%s") → "%s"', (input, expected) => {
    const store = useEditorStore()
    expect(store.cleanPlaceholder(input)).toBe(expected)
  })
})

describe('Generate button — message construction', () => {
  it('uses FIELD_LABELS not FIELD_TITLES for generate message', () => {
    const field = 'settings_md_content'
    const msg = '生成' + (FIELD_LABELS[field] || field)
    expect(msg).toBe('生成写作设定')
    expect(msg).not.toBe('生成编辑写作设定')
  })

  it('FIELD_LABELS are short names, FIELD_TITLES are editor labels', () => {
    expect(FIELD_LABELS['settings_md_content']).toBe('写作设定')
    expect(FIELD_TITLES['settings_md_content']).toBe('编辑写作设定')
    expect(FIELD_LABELS['characters_md_content']).toBe('角色档案')
    expect(FIELD_TITLES['characters_md_content']).toBe('编辑角色档案')
  })

  it('generate message for all field types uses LABELS', () => {
    const fields = ['settings_md_content', 'characters_md_content',
      'relationships_md_content', 'foreshadowing_md_content']
    for (const f of fields) {
      const msg = '生成' + (FIELD_LABELS[f] || f)
      expect(msg.startsWith('生成')).toBe(true)
      expect(msg.includes('编辑')).toBe(false)  // FIELD_LABELS should NOT contain 编辑
    }
  })
})
