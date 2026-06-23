import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChatMessage, AgentActivityStep } from '@/types'
import * as api from '@/api'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const streamingContent = ref('')
  const streamingActivity = ref<AgentActivityStep[]>([])
  const reasoningContent = ref('')
  const showThinking = ref(false)
  const thinkingCollapsed = ref(false)

  function addUserMessage(content: string) {
    messages.value.push({ role: 'user', content })
  }

  function addAgentMessage(content: string, thinking?: string, activity?: AgentActivityStep[]) {
    const msg: ChatMessage = { role: 'assistant', content }
    if (thinking) msg.thinking = thinking
    if (activity?.length) msg.activity = activity
    messages.value.push(msg)
  }

  function clearMessages() {
    messages.value = []
    streamingContent.value = ''
    streamingActivity.value = []
    reasoningContent.value = ''
    showThinking.value = false
    thinkingCollapsed.value = false
  }

  async function loadHistory(rounds: number = 10) {
    const data = await api.getChatHistory(rounds)
    if (data.messages?.length) {
      messages.value = data.messages
    }
  }

  async function clearChat() {
    await api.clearChat()
    clearMessages()
  }

  return {
    messages,
    streamingContent,
    streamingActivity,
    reasoningContent,
    showThinking,
    thinkingCollapsed,
    addUserMessage,
    addAgentMessage,
    clearMessages,
    loadHistory,
    clearChat,
  }
})
