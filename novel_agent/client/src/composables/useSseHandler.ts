import type { SseEvent, AgentActivityStep, NovelState } from '@/types'
import type { useChatStore, useEditorStore } from '@/stores'

type ChatStore = ReturnType<typeof useChatStore>
type EditorStore = ReturnType<typeof useEditorStore>

type SseEventOf<T extends string> = Extract<SseEvent, { type: T }>

interface SseHandlerHooks {
  onError?: (evt: SseEventOf<'error'>) => void
  onChapterTitle?: (title: string) => void
  onGenerateStart?: (evt: SseEventOf<'generate_start'>) => void
  onGenerateDone?: (evt: SseEventOf<'generate_done'>) => void
  onGenerateReset?: (evt: SseEventOf<'generate_reset'>) => void
  onHandoff?: (evt: SseEventOf<'handoff'>) => void
  onPlanGenerated?: (evt: SseEventOf<'plan_generated'>) => void
  onPlanReplan?: (evt: SseEventOf<'plan_replan'>) => void
  onInterrupt?: (evt: SseEventOf<'interrupt'>) => void
  collapseThinkingOnToken?: boolean
}

function upsertActivityStep(chatStore: ChatStore, step: AgentActivityStep) {
  const steps = chatStore.streamingActivity
  const idx = steps.findIndex(
    (s) =>
      s.kind === step.kind
      && (step.tool ? s.tool === step.tool : s.agent === step.agent)
      && s.label === step.label,
  )
  if (idx >= 0) {
    steps[idx] = { ...steps[idx], ...step }
  } else {
    steps.push(step)
  }
}

export function createSseHandler(
  chatStore: ChatStore,
  editorStore: EditorStore,
  hooks: SseHandlerHooks = {},
) {
  const collapse = hooks.collapseThinkingOnToken ?? true

  return function handleSseEvent(evt: SseEvent) {
    switch (evt.type) {
      case 'error':
        if (hooks.onError) hooks.onError(evt)
        else throw new Error(evt.error || '未知错误')
        break
      case 'token':
        if (collapse && chatStore.showThinking && chatStore.reasoningContent) chatStore.thinkingCollapsed = true
        chatStore.streamingContent += evt.token || ''
        break
      case 'reasoning':
        chatStore.showThinking = true
        chatStore.thinkingCollapsed = false
        chatStore.reasoningContent += evt.token || ''
        break
      case 'assistant_reply':
        if (collapse && chatStore.showThinking && chatStore.reasoningContent) chatStore.thinkingCollapsed = true
        chatStore.streamingContent = evt.content || ''
        if (evt.activity?.length) {
          chatStore.streamingActivity = evt.activity
        }
        break
      case 'agent_activity':
        if (evt.step) {
          upsertActivityStep(chatStore, evt.step)
        }
        break
      case 'task_complete':
        break
      case 'chapter_title':
        editorStore.pendingChapterTitle = evt.title || ''
        hooks.onChapterTitle?.(evt.title || '')
        break
      case 'generate_start':
        hooks.onGenerateStart?.(evt)
        editorStore.handleGenerateEvent(evt)
        break
      case 'generate_token':
        editorStore.handleGenerateEvent(evt)
        break
      case 'generate_done':
        hooks.onGenerateDone?.(evt)
        editorStore.handleGenerateEvent(evt)
        break
      case 'generate_reset':
        hooks.onGenerateReset?.(evt)
        editorStore.handleGenerateEvent(evt)
        break
      case 'field_content':
        editorStore.handleGenerateEvent(evt)
        break
      case 'interrupt':
        hooks.onInterrupt?.(evt)
        break
      case 'handoff':
        hooks.onHandoff?.(evt)
        break
      case 'subagent_token':
        break
      case 'subagent_tool_call':
        break
      case 'plan_generated':
        hooks.onPlanGenerated?.(evt)
        break
      case 'plan_step_start':
      case 'plan_step_complete':
      case 'plan_completed':
      case 'done':
        break
      case 'plan_replan':
        hooks.onPlanReplan?.(evt)
        break
      case 'daily_sync_start':
      case 'daily_sync_done':
        break
      case 'state':
        if (evt.type === 'state' && evt.state) {
          editorStore.applyRemoteState(evt.state)
        }
        break
      case 'critic_review_start':
      case 'critic_review_done':
        break
    }
  }
}

interface ConsumeStreamOptions {
  chatStore: ChatStore
  editorStore: EditorStore
  handleEvent: (evt: SseEvent) => void
  includeThinking?: boolean
  onSuccess?: () => void
  onAbort?: () => void
  controller?: AbortController | null
}

export async function consumeStream(
  stream: AsyncGenerator<SseEvent>,
  opts: ConsumeStreamOptions,
) {
  const { chatStore, editorStore, handleEvent, includeThinking = false, onSuccess, onAbort, controller } = opts
  try {
    for await (const evt of stream) handleEvent(evt)
    if (chatStore.streamingContent || chatStore.streamingActivity.length) {
      chatStore.addAgentMessage(
        chatStore.streamingContent,
        includeThinking ? (chatStore.reasoningContent || undefined) : undefined,
        chatStore.streamingActivity.length ? [...chatStore.streamingActivity] : undefined,
      )
    }
    // Wait one frame so Vue renders the new message before clearing streaming state
    await new Promise(resolve => setTimeout(resolve, 0))
    chatStore.streamingContent = ''
    chatStore.streamingActivity = []
    chatStore.reasoningContent = ''
    chatStore.showThinking = false
    onSuccess?.()
  } catch (e: any) {
    if (e.name === 'AbortError') {
      onAbort?.()
      if (chatStore.streamingContent || chatStore.streamingActivity.length) {
        chatStore.addAgentMessage(
          chatStore.streamingContent,
          includeThinking ? (chatStore.reasoningContent || undefined) : undefined,
          chatStore.streamingActivity.length ? [...chatStore.streamingActivity] : undefined,
        )
      }
      chatStore.streamingContent = ''
      chatStore.streamingActivity = []
      chatStore.reasoningContent = ''
      chatStore.addAgentMessage('⏹ 已停止')
    } else {
      chatStore.addAgentMessage('出错了：' + (e.message || '未知错误'))
    }
    chatStore.showThinking = false
    chatStore.reasoningContent = ''
  } finally {
    if (!controller || editorStore.abortController === controller) {
      editorStore.stopGeneration()
    }
  }
}
