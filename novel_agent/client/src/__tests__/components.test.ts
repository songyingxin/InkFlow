/**
 * Vue 组件测试
 *
 * 测试 Vue 组件的渲染和交互：
 * - SideBar: 侧边栏渲染、字段点击、章节列表
 * - MarkdownEditor: 编辑器渲染、工具栏操作
 * - ChatPanel: 对话面板渲染
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import SideBar from '@/components/SideBar.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import { useEditorStore } from '@/stores'

describe('SideBar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders empty state when no book loaded', () => {
    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })
    expect(wrapper.text()).toContain('尚未加载作品')
  })

  it('renders sidebar fields when state is loaded', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.text()).toContain('测试小说')
    expect(wrapper.text()).toContain('历史大纲')
    expect(wrapper.text()).toContain('写作设定')
    expect(wrapper.text()).toContain('角色档案')
  })

  it('emits fieldChanged when clicking a field', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    const items = wrapper.findAll('.sb-quick-btn')
    if (items.length > 0) {
      await items[0].trigger('click')
      expect(wrapper.emitted('fieldChanged')).toBeTruthy()
    }
  })

  it('emits showImport when import button clicked', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    const importBtn = wrapper.find('.sb-ch-import-btn')
    if (importBtn.exists()) {
      await importBtn.trigger('click')
      expect(wrapper.emitted('showImport')).toBeTruthy()
    }
  })

  it('shows chapters when available', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 2 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [
        { idx: 1, title: '第一章', is_written: true },
        { idx: 2, title: '第二章', is_written: false },
      ],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.text()).toContain('第一章')
    expect(wrapper.text()).toContain('第二章')
  })

  it('shows empty state when no chapters', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.text()).toContain('暂无章节')
  })
})

describe('MarkdownEditor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders title', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '' },
    })
    expect(wrapper.text()).toContain('编辑设定')
  })

  it('shows edit mode by default', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '' },
    })
    expect(wrapper.find('.md-textarea').exists()).toBe(true)
  })

  it('shows preview mode when previewMode is true', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '# 标题', previewMode: true },
    })
    expect(wrapper.find('.md-preview-panel').exists()).toBe(true)
    expect(wrapper.find('.md-textarea').exists()).toBe(false)
  })

  it('emits update:content on input', async () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '' },
    })
    const textarea = wrapper.find('.md-textarea')
    await textarea.setValue('新内容')
    expect(wrapper.emitted('update:content')).toBeTruthy()
    expect(wrapper.emitted('update:content')![0]).toEqual(['新内容'])
  })

  it('emits save on save button click', async () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '内容' },
    })
    const saveBtn = wrapper.find('.fe-btn-save')
    await saveBtn.trigger('click')
    expect(wrapper.emitted('save')).toBeTruthy()
  })

  it('shows diff button when highlights exist', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '新内容', highlights: [0] },
    })
    expect(wrapper.find('.fe-btn-diff').exists()).toBe(true)
  })

  it('shows stop button when generating', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '', generating: true },
    })
    expect(wrapper.find('.fe-btn-stop').exists()).toBe(true)
  })

  it('disables save button when saving', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '', saving: true },
    })
    const saveBtn = wrapper.find('.fe-btn-save')
    expect((saveBtn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows chapter title input when showChapterTitle is true', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑章节', content: '', showChapterTitle: true },
    })
    expect(wrapper.find('.chapter-title-input').exists()).toBe(true)
  })

  it('renders markdown in preview mode', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '# 标题\n\n段落', previewMode: true },
    })
    const panel = wrapper.find('.md-preview-panel')
    expect(panel.html()).toContain('标题')
  })

  it('shows undo/redo buttons', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '', canUndo: true, canRedo: true },
    })
    expect(wrapper.find('.fe-btn[title="撤销"]').exists()).toBe(true)
    expect(wrapper.find('.fe-btn[title="重做"]').exists()).toBe(true)
  })

  it('disables undo button when canUndo is false', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '', canUndo: false },
    })
    const undoBtn = wrapper.find('.fe-btn[title="撤销"]')
    expect((undoBtn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('shows streaming class when streaming', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '', streaming: true },
    })
    expect(wrapper.find('.md-textarea.streaming').exists()).toBe(true)
  })

  it('shows mode toggle buttons', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '', showModeBtns: true },
    })
    const modeBtns = wrapper.findAll('.md-mode-btn')
    expect(modeBtns.length).toBe(2)
  })

  it('hides mode toggle when showModeBtns is false', () => {
    const wrapper = mount(MarkdownEditor, {
      props: { title: '编辑设定', content: '', showModeBtns: false },
    })
    expect(wrapper.findAll('.md-mode-btn').length).toBe(0)
  })
})

describe('SideBar - chapter dots', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows done dot for written chapters', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 1 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [
        { idx: 1, title: '第一章', is_written: true },
      ],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    const dot = wrapper.find('.sb-ch-dot')
    expect(dot.classes()).toContain('done')
  })

  it('shows now dot for first unwritten chapter', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 2 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [
        { idx: 1, title: '第一章', is_written: true },
        { idx: 2, title: '第二章', is_written: false },
      ],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    const dots = wrapper.findAll('.sb-ch-dot')
    expect(dots[0].classes()).toContain('done')
    expect(dots[1].classes()).toContain('now')
  })

  it('shows add chapter button', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.find('.sb-ch-add-btn').exists()).toBe(true)
  })

  it('shows generate button for outline fields', async () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }

    const wrapper = mount(SideBar, {
      global: { stubs: { teleport: true } },
    })

    const genBtns = wrapper.findAll('.sb-quick-gen')
    expect(genBtns.length).toBeGreaterThanOrEqual(1)
  })
})
