/**
 * LandingPage 组件测试
 *
 * 测试书库首页的渲染和交互：
 * - 空书库状态
 * - 书籍列表渲染
 * - 新建小说弹窗
 * - 删除确认弹窗
 * - 加载和错误状态
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import LandingPage from '@/pages/LandingPage.vue'
import { useBookStore } from '@/stores'

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

vi.mock('@/api', () => ({
  listBooks: vi.fn().mockResolvedValue({ books: [] }),
  createBook: vi.fn(),
  selectBook: vi.fn(),
  deleteBook: vi.fn(),
}))

describe('LandingPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders logo', () => {
    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })
    expect(wrapper.text()).toContain('墨')
    expect(wrapper.text()).toContain('灵')
  })

  it('shows empty state when no books', async () => {
    const store = useBookStore()
    store.books = []
    store.loading = false
    store.error = ''

    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.text()).toContain('尚无作品')
  })

  it('shows book cards when books exist', async () => {
    const store = useBookStore()
    store.books = [
      { name: 'test1', title: '测试小说1', total_chapters: 5 },
      { name: 'test2', title: '测试小说2', total_chapters: 10 },
    ]
    store.loading = false
    store.error = ''

    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.text()).toContain('测试小说1')
    expect(wrapper.text()).toContain('测试小说2')
    expect(wrapper.text()).toContain('5 章')
    expect(wrapper.text()).toContain('10 章')
  })

  it('shows loading state', () => {
    const store = useBookStore()
    store.loading = true

    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.text()).toContain('加载书库中')
  })

  it('shows error state', () => {
    const store = useBookStore()
    store.loading = false
    store.error = '连接失败'

    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.text()).toContain('连接失败')
    expect(wrapper.find('.error-retry').exists()).toBe(true)
  })

  it('has create button', () => {
    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.find('.create-btn').exists()).toBe(true)
    expect(wrapper.text()).toContain('新建小说')
  })

  it('shows delete button on book cards', () => {
    const store = useBookStore()
    store.books = [{ name: 'test1', title: '测试小说', total_chapters: 1 }]
    store.loading = false
    store.error = ''

    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    expect(wrapper.find('.book-card-del').exists()).toBe(true)
  })

  it('shows create modal when create button clicked', async () => {
    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    await wrapper.find('.create-btn').trigger('click')
    expect(wrapper.find('.modal-overlay').exists()).toBe(true)
    expect(wrapper.text()).toContain('新建小说')
  })

  it('has cancel button in create modal', async () => {
    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    await wrapper.find('.create-btn').trigger('click')
    expect(wrapper.find('.modal-btn-cancel').exists()).toBe(true)
  })

  it('has input in create modal', async () => {
    const wrapper = mount(LandingPage, {
      global: { stubs: { teleport: true, routerLink: true } },
    })

    await wrapper.find('.create-btn').trigger('click')
    expect(wrapper.find('.modal-input').exists()).toBe(true)
  })
})
