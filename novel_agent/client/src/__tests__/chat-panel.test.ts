/**
 * ChatPanel 组件测试
 *
 * 测试对话面板的渲染和交互：
 * - 空状态欢迎界面
 * - 消息列表渲染
 * - 流式内容显示
 * - 深度思考折叠/展开
 * - 发送消息交互
 * - SSE 事件处理
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import ChatPanel from '@/components/ChatPanel.vue'
import { useChatStore, useEditorStore } from '@/stores'

vi.mock('@/api', () => ({
  chatStream: vi.fn(),
  resumeStream: vi.fn(),
}))

describe('ChatPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders welcome state when no messages', () => {
    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })
    expect(wrapper.text()).toContain('你好，我是你的创作助手')
    expect(wrapper.text()).toContain('生成大纲')
    expect(wrapper.text()).toContain('续写下一章')
  })

  it('renders user and assistant messages', async () => {
    const chatStore = useChatStore()
    chatStore.addUserMessage('你好')
    chatStore.addAgentMessage('你好！有什么可以帮你的？')

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.text()).toContain('你好')
    expect(wrapper.text()).toContain('你好！有什么可以帮你的？')
  })

  it('shows user avatar as 我', async () => {
    const chatStore = useChatStore()
    chatStore.addUserMessage('测试消息')

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    const avatars = wrapper.findAll('.msg-avatar')
    expect(avatars.length).toBeGreaterThanOrEqual(1)
    expect(avatars[0].text()).toBe('我')
  })

  it('shows agent avatar as 墨', async () => {
    const chatStore = useChatStore()
    chatStore.addAgentMessage('回复消息')

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    const avatars = wrapper.findAll('.msg-avatar')
    const agentAvatars = avatars.filter(a => a.text() === '墨')
    expect(agentAvatars.length).toBeGreaterThanOrEqual(1)
  })

  it('renders streaming content', async () => {
    const chatStore = useChatStore()
    chatStore.streamingContent = '正在生成...'

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.text()).toContain('正在生成...')
    expect(wrapper.find('.streaming-cursor').exists()).toBe(true)
  })

  it('shows thinking block when showThinking is true', async () => {
    const chatStore = useChatStore()
    chatStore.showThinking = true
    chatStore.reasoningContent = '深度思考内容...'

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.text()).toContain('深度思考')
  })

  it('renders history thinking in messages', async () => {
    const chatStore = useChatStore()
    chatStore.addAgentMessage('回复内容', '这是思考过程')

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.text()).toContain('已深度思考')
    expect(wrapper.text()).toContain('回复内容')
  })

  it('shows send button when not generating', () => {
    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.find('.chat-send-btn').exists()).toBe(true)
    expect(wrapper.find('.chat-stop-btn').exists()).toBe(false)
  })

  it('shows stop button when generating', () => {
    const editorStore = useEditorStore()
    editorStore.startGeneration()

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.find('.chat-stop-btn').exists()).toBe(true)
    expect(wrapper.find('.chat-send-btn').exists()).toBe(false)
  })

  it('has textarea for input', () => {
    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.find('.chat-input').exists()).toBe(true)
  })

  it('has clear chat button', () => {
    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    expect(wrapper.find('.chat-clear-btn').exists()).toBe(true)
  })

  it('renders suggestion buttons', () => {
    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    const suggestions = wrapper.findAll('.chat-suggestion')
    expect(suggestions.length).toBe(4)
  })

  it('renders markdown in agent messages', async () => {
    const chatStore = useChatStore()
    chatStore.addAgentMessage('# 标题\n\n**加粗**内容')

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    const mdContent = wrapper.find('.chat-md')
    expect(mdContent.exists()).toBe(true)
  })

  it('maintains message order', async () => {
    const chatStore = useChatStore()
    chatStore.addUserMessage('第一条')
    chatStore.addAgentMessage('回复一')
    chatStore.addUserMessage('第二条')

    const wrapper = mount(ChatPanel, {
      global: { stubs: { teleport: true } },
    })

    const messages = wrapper.findAll('.msg')
    expect(messages.length).toBe(3)
    expect(messages[0].classes()).toContain('user')
    expect(messages[1].classes()).toContain('assistant')
    expect(messages[2].classes()).toContain('user')
  })
})
