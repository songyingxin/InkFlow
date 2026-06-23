/**
 * EditorPage 集成测试
 *
 * 测试编辑器页面的核心集成逻辑：
 * - 布局渲染（侧边栏 + 编辑区 + 对话面板）
 * - 返回书库按钮
 * - 侧边栏切换
 * - 空状态提示
 * - 字段编辑切换
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import EditorPage from '@/pages/EditorPage.vue'
import { useEditorStore, useChatStore } from '@/stores'

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

vi.mock('@/api', () => ({
  chatStream: vi.fn(),
  resumeStream: vi.fn(),
  getState: vi.fn(),
  getChapterContent: vi.fn(),
  updateChapter: vi.fn(),
  addChapter: vi.fn(),
  updateField: vi.fn(),
  deleteChapter: vi.fn(),
}))

describe('EditorPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders header with book name', () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试小说',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }

    const wrapper = mount(EditorPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.text()).toContain('测试小说')
  })

  it('shows sidebar toggle button', () => {
    const wrapper = mount(EditorPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.find('.sidebar-toggle').exists()).toBe(true)
  })

  it('shows back to library button', () => {
    const wrapper = mount(EditorPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.text()).toContain('书库')
  })

  it('renders three-column layout', () => {
    const wrapper = mount(EditorPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.find('.sidebar').exists() || wrapper.findComponent({ name: 'SideBar' }).exists()).toBe(true)
    expect(wrapper.find('.chat-area').exists() || wrapper.findComponent({ name: 'ChatPanel' }).exists()).toBe(true)
  })

  it('shows placeholder when no field is being edited', () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试小说',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }
    store.editingField = ''

    const wrapper = mount(EditorPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.text()).toContain('墨灵')
  })

  it('shows chapter info when last written chapter exists', () => {
    const store = useEditorStore()
    store.currentState = {
      current_book_name: '测试小说',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 1 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [
        { idx: 1, title: '第一章', is_written: true, content_summary: '摘要' },
      ],
      messages: [],
    }
    store.editingField = ''

    const wrapper = mount(EditorPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.text()).toContain('第一章')
  })

  it('toggles sidebar visibility', async () => {
    const store = useEditorStore()
    expect(store.sidebarVisible).toBe(true)

    store.toggleSidebar()
    expect(store.sidebarVisible).toBe(false)

    store.toggleSidebar()
    expect(store.sidebarVisible).toBe(true)
  })
})
