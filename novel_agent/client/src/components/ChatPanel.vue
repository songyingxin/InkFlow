<template>
  <div class="chat-area">
    <div class="resize-handle" @mousedown="startResize">
      <div class="resize-handle-line" />
    </div>

    <div class="chat-header">
      <span class="chat-header-title">对话</span>
      <button class="chat-clear-btn" @click="handleClearChat" title="清空对话" aria-label="清空对话">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="2,4 3.5,4 14,4" /><path d="M5,4V2.5A1.5,1.5,0,0,1,6.5,1h3A1.5,1.5,0,0,1,11,2.5V4" /><path d="M12.5,4v9.5a1.5,1.5,0,0,1-1.5,1.5H5A1.5,1.5,0,0,1,3.5,13.5V4" />
        </svg>
      </button>
    </div>

    <div class="chat-msgs" ref="msgsContainer">
      <div v-if="!chatStore.messages.length && !chatStore.streamingContent" class="chat-welcome">
        <div class="chat-welcome-icon">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2a7 7 0 0 1 7 7c0 3-2 5.5-4 7l-3 3-3-3c-2-1.5-4-4-4-7a7 7 0 0 1 7-7z" /><circle cx="12" cy="9" r="2.5" />
          </svg>
        </div>
        <div class="chat-welcome-text">你好，我是你的创作助手</div>
        <div class="chat-welcome-sub">可以帮你生成大纲、续写章节、管理伏笔与设定</div>
        <div class="chat-suggestions">
          <div class="chat-suggestion" @click="useSuggestion('生成大纲')">生成大纲</div>
          <div class="chat-suggestion" @click="useSuggestion('续写下一章')">续写下一章</div>
          <div class="chat-suggestion" @click="useSuggestion('更新写作设定')">更新设定</div>
          <div class="chat-suggestion" @click="useSuggestion('伏笔管理')">伏笔管理</div>
        </div>
      </div>

      <template v-for="(msg, i) in chatStore.messages" :key="i">
        <div class="msg" :class="msg.role">
          <div class="msg-avatar">
            <template v-if="msg.role === 'user'">我</template>
            <template v-else>墨</template>
          </div>
          <div class="msg-body">
            <div class="msg-name">{{ msg.role === 'user' ? '我' : '墨灵' }}</div>
            <div class="msg-bubble">
              <div v-if="msg.thinking" class="thinking-block">
                <div
                  class="thinking-header collapsed"
                  @click="toggleHistoryThinking(i)"
                >
                  <span>已深度思考</span>
                  <span class="thinking-toggle">{{ historyThinkingOpen[i] ? '▾' : '▸' }}</span>
                </div>
                <div v-if="historyThinkingOpen[i]" class="thinking-body" v-text="msg.thinking" />
              </div>
              <div v-if="msg.activity?.length" class="thinking-block activity-block">
                <div
                  class="thinking-header collapsed"
                  @click="toggleHistoryActivity(i)"
                >
                  <span>执行过程（{{ msg.activity.length }} 步）</span>
                  <span class="thinking-toggle">{{ historyActivityOpen[i] ? '▾' : '▸' }}</span>
                </div>
                <ul v-if="historyActivityOpen[i]" class="activity-list">
                  <li v-for="(step, si) in msg.activity" :key="si" class="activity-item">
                    <span class="activity-status" :class="step.status || 'done'">●</span>
                    <span>{{ step.label }}</span>
                  </li>
                </ul>
              </div>
              <div v-if="msg.role === 'user'" class="msg-text" v-text="msg.content" />
              <div v-else class="chat-md" v-html="renderMarkdown(msg.content)" />
            </div>
          </div>
        </div>
      </template>

      <div v-if="chatStore.streamingContent || chatStore.showThinking" class="msg agent">
        <div class="msg-avatar">墨</div>
        <div class="msg-body">
          <div class="msg-name">墨灵</div>
          <div class="msg-bubble">
            <div v-if="chatStore.showThinking" class="thinking-block">
              <div class="thinking-header" :class="{ collapsed: chatStore.thinkingCollapsed }" @click="chatStore.thinkingCollapsed = !chatStore.thinkingCollapsed">
                <span class="thinking-dots" v-if="!chatStore.thinkingCollapsed">
                  <span class="thinking-dot" />
                  <span class="thinking-dot" style="animation-delay: 0.2s" />
                  <span class="thinking-dot" style="animation-delay: 0.4s" />
                </span>
                <span>{{ chatStore.thinkingCollapsed ? '已深度思考' : '深度思考中' }}</span>
                <span class="thinking-toggle">{{ chatStore.thinkingCollapsed ? '▸' : '▾' }}</span>
              </div>
              <div v-if="!chatStore.thinkingCollapsed" class="thinking-body" v-text="chatStore.reasoningContent" />
            </div>
            <div v-if="chatStore.streamingActivity.length" class="thinking-block activity-block">
              <div class="thinking-header collapsed" @click="streamingActivityCollapsed = !streamingActivityCollapsed">
                <span>{{ editorStore.isGenerating ? '执行中' : '执行过程' }}（{{ chatStore.streamingActivity.length }} 步）</span>
                <span class="thinking-toggle">{{ streamingActivityCollapsed ? '▸' : '▾' }}</span>
              </div>
              <ul v-if="!streamingActivityCollapsed" class="activity-list">
                <li v-for="(step, si) in chatStore.streamingActivity" :key="si" class="activity-item">
                  <span class="activity-status" :class="step.status || 'done'">●</span>
                  <span>{{ step.label }}</span>
                </li>
              </ul>
            </div>
            <div v-if="chatStore.streamingContent" class="streaming-content">
              <div class="chat-md" v-html="throttledStreamingHtml" />
              <span class="streaming-cursor" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="chat-input-area">
      <div v-if="mentionState.active" class="mention-menu" ref="mentionMenuRef">
        <div class="mention-menu-header">引用上下文</div>
        <button
          v-for="item in mentionState.items"
          :key="item.key"
          class="mention-item"
          :class="{ active: mentionState.selected === item.key }"
          @mousedown.prevent="insertMention(item)"
        >
          <span class="mention-item-icon">{{ item.icon }}</span>
          <span class="mention-item-label">{{ item.label }}</span>
          <span class="mention-item-type">{{ item.type }}</span>
        </button>
      </div>
      <div class="chat-input-wrap" :class="{ 'has-mentions': mentions.length }">
        <div v-if="mentions.length" class="mentions-bar">
          <span
            v-for="(m, i) in mentions"
            :key="i"
            class="mention-chip"
          >
            {{ m.label }}
            <button class="mention-chip-x" @click="removeMention(i)">×</button>
          </span>
        </div>
        <textarea
          ref="chatInputRef"
          v-model="inputText"
          class="chat-input"
          rows="1"
          placeholder="输入你的创作需求... (@ 引用章节/角色/设定)"
          @keydown.enter.exact.prevent="sendMessage"
          @keydown.up.prevent="moveMention(-1)"
          @keydown.down.prevent="moveMention(1)"
          @keydown.escape="closeMention"
          @input="onInputChange"
        />
        <button v-if="!editorStore.isGenerating" class="chat-send-btn" @click="sendMessage" title="发送" aria-label="发送消息">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
        <button v-else class="chat-stop-btn" @click="editorStore.stopGeneration()" title="停止生成" aria-label="停止生成">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="2" /></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onUnmounted } from 'vue'
import { useChatStore, useEditorStore } from '@/stores'
import { chatStream } from '@/api'
import { marked } from 'marked'
import type { SseEvent } from '@/types'
import { consumeStream } from '@/composables/useSseHandler'

const props = defineProps<{
  confirmUnsaved?: (actionLabel: string) => Promise<'cancel' | 'discard' | 'save'>
  saveCurrent?: () => Promise<void>
  /** 由 EditorPage 注入，确保 chapter_title / generate_* 等事件同步到编辑器 */
  handleEvent: (evt: SseEvent) => void
}>()

const chatStore = useChatStore()
const editorStore = useEditorStore()

const inputText = ref('')
const chatInputRef = ref<HTMLTextAreaElement>()
const msgsContainer = ref<HTMLDivElement>()
const mentionMenuRef = ref<HTMLDivElement>()
const historyThinkingOpen = ref<Record<number, boolean>>({})
const historyActivityOpen = ref<Record<number, boolean>>({})
const streamingActivityCollapsed = ref(false)

interface MentionItem {
  key: string
  label: string
  type: string
  icon: string
  field?: string
  chapterIdx?: number
}

interface Mention {
  key: string
  label: string
  field?: string
  chapterIdx?: number
}

const mentions = ref<Mention[]>([])
const mentionState = ref<{ active: boolean; items: MentionItem[]; selected: string; query: string; startPos: number }>({
  active: false,
  items: [],
  selected: '',
  query: '',
  startPos: 0,
})

function buildMentionItems(query: string): MentionItem[] {
  const items: MentionItem[] = []
  const q = query.toLowerCase()
  const es = editorStore

  for (const ch of es.chapters) {
    if (!ch.is_written && !ch.title) continue
    const label = '第' + ch.idx + '章 ' + (ch.title || '')
    if (!q || label.toLowerCase().includes(q) || String(ch.idx).includes(q)) {
      items.push({ key: 'ch_' + ch.idx, label, type: '章节', icon: '§', chapterIdx: ch.idx })
    }
  }

  const fields: [string, string, string][] = [
    ['settings_md_content', '写作设定', '⚙'],
    ['outline_future_md_content', '未来大纲', '📜'],
    ['characters_md_content', '角色档案', '👤'],
    ['relationships_md_content', '关系图谱', '🔗'],
    ['foreshadowing_md_content', '伏笔清单', '✦'],
  ]
  for (const [field, label, icon] of fields) {
    if (!q || label.toLowerCase().includes(q)) {
      items.push({ key: 'field_' + field, label, type: '设定', icon, field })
    }
  }

  return items.slice(0, 12)
}

function onInputChange(e: Event) {
  autoResize()
  const ta = e.target as HTMLTextAreaElement
  const pos = ta.selectionStart
  const text = ta.value.substring(0, pos)
  const atIdx = text.lastIndexOf('@')
  if (atIdx >= 0) {
    const after = text.substring(atIdx + 1)
    if (after.length <= 20 && !after.includes(' ') && !after.includes('\n')) {
      const items = buildMentionItems(after)
      if (items.length) {
        mentionState.value = { active: true, items, selected: items[0].key, query: after, startPos: atIdx }
        return
      }
    }
  }
  closeMention()
}

function closeMention() {
  mentionState.value.active = false
}

function moveMention(dir: number) {
  if (!mentionState.value.active) return
  const items = mentionState.value.items
  const idx = items.findIndex(i => i.key === mentionState.value.selected)
  const next = (idx + dir + items.length) % items.length
  mentionState.value.selected = items[next].key
}

function insertMention(item: MentionItem) {
  const ta = chatInputRef.value
  if (!ta) return
  const before = ta.value.substring(0, mentionState.value.startPos)
  const after = ta.value.substring(ta.selectionStart)
  inputText.value = before + '@' + item.label + ' ' + after
  closeMention()
  nextTick(() => {
    ta.focus()
    const pos = before.length + item.label.length + 2
    ta.setSelectionRange(pos, pos)
    autoResize()
  })
  if (!mentions.value.find(m => m.key === item.key)) {
    mentions.value.push({ key: item.key, label: item.label, field: item.field, chapterIdx: item.chapterIdx })
  }
}

function removeMention(i: number) {
  mentions.value.splice(i, 1)
}

function expandMentions(text: string): string {
  if (!mentions.value.length) return text
  const parts: string[] = [text]
  for (const m of mentions.value) {
    if (m.chapterIdx !== undefined) {
      const ch = editorStore.chapters.find(c => c.idx === m.chapterIdx)
      if (ch) {
        parts.push('\n\n---\n[引用：第' + ch.idx + '章 ' + (ch.title || '') + ']\n' + (ch.content_summary || ''))
      }
    } else if (m.field) {
      const v = editorStore.fieldValues[m.field] || ''
      const cleaned = editorStore.cleanPlaceholder(v)
      if (cleaned) {
        parts.push('\n\n---\n[引用：' + m.label + ']\n' + cleaned)
      }
    }
  }
  return parts.join('')
}

function toggleHistoryThinking(i: number) {
  historyThinkingOpen.value[i] = !historyThinkingOpen.value[i]
}

function toggleHistoryActivity(i: number) {
  historyActivityOpen.value[i] = !historyActivityOpen.value[i]
}

function renderMarkdown(md: string) {
  if (!md) return ''
  return marked.parse(md) as string
}

/** 流式生成时防闪烁：throttle markdown 渲染到 ~80ms */
const throttledStreamingHtml = ref('')
let _throttleTimer: ReturnType<typeof setTimeout> | null = null
let _nextRaw = ''

function _flushThrottle() {
  _throttleTimer = null
  throttledStreamingHtml.value = renderMarkdown(_nextRaw)
}

watch(
  () => chatStore.streamingContent,
  (raw) => {
    _nextRaw = raw
    if (!_throttleTimer) {
      _throttleTimer = setTimeout(_flushThrottle, 100)
    }
  },
)

onUnmounted(() => {
  if (_throttleTimer) clearTimeout(_throttleTimer)
})

function autoResize() {
  const ta = chatInputRef.value
  if (!ta) return
  ta.style.height = 'auto'
  ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'
}

function useSuggestion(text: string) {
  inputText.value = text
  sendMessage()
}

async function handleClearChat() {
  await chatStore.clearChat()
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || editorStore.isGenerating) return

  if (editorStore.isDirty || editorStore.hasUnsavedGenerated) {
    if (props.confirmUnsaved) {
      const action = await props.confirmUnsaved('发送')
      if (action === 'cancel') return
      if (action === 'save' && props.saveCurrent) await props.saveCurrent()
    } else {
      editorStore.resetDirty()
    }
  }

  const expandedText = expandMentions(text)
  inputText.value = ''
  mentions.value = []
  if (chatInputRef.value) chatInputRef.value.style.height = 'auto'

  chatStore.addUserMessage(text)
  chatStore.streamingContent = ''
  chatStore.streamingActivity = []
  chatStore.reasoningContent = ''
  chatStore.showThinking = false
  chatStore.thinkingCollapsed = false
  streamingActivityCollapsed.value = false

  editorStore.startGeneration()
  const myController = editorStore.abortController

  const stream = chatStream(expandedText, editorStore.fieldValues, myController?.signal, text)
  await consumeStream(stream, {
    chatStore, editorStore, handleEvent,
    includeThinking: true,
    controller: myController,
  })
}

function handleEvent(evt: SseEvent) {
  ;(props.handleEvent)(evt)
}

watch(
  () => [chatStore.messages.length, chatStore.streamingContent],
  () => { nextTick(() => { if (msgsContainer.value) msgsContainer.value.scrollTop = msgsContainer.value.scrollHeight }) },
  { deep: true }
)

watch(
  () => chatStore.messages.length,
  () => { historyThinkingOpen.value = {}; historyActivityOpen.value = {} },
)

interface ResizeState {
  mainEl: HTMLElement
  startX: number
  chatColumnWidth: number
  sidebarHidden: boolean
}

function startResize(e: MouseEvent) {
  e.preventDefault()
  const chatArea = (e.target as HTMLElement).closest('.chat-area') as HTMLElement
  if (!chatArea) return
  const mainEl = chatArea.parentElement as HTMLElement
  if (!mainEl) return

  const sidebarHidden = mainEl.classList.contains('sidebar-hidden')
  const startX = e.clientX
  const chatColumnWidth = chatArea.getBoundingClientRect().width

  const state: ResizeState = { mainEl, startX, chatColumnWidth, sidebarHidden }

  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeUp)

  function onResizeMove(ev: MouseEvent) {
    onResizeMoveFn(ev, state)
  }

  function onResizeUp() {
    document.removeEventListener('mousemove', onResizeMove)
    document.removeEventListener('mouseup', onResizeUp)
  }
}

function onResizeMoveFn(ev: MouseEvent, state: ResizeState) {
  const dx = state.startX - ev.clientX
  const newWidth = Math.min(
    Math.floor(window.innerWidth * 0.5),
    Math.max(300, state.chatColumnWidth + dx)
  )
  const col1 = state.sidebarHidden ? '0' : 'var(--sidebar-w)'
  state.mainEl.style.gridTemplateColumns = col1 + ' 1fr ' + newWidth + 'px'
  state.mainEl.style.transition = 'none'
}
</script>

<style scoped>
.chat-area {
  background: var(--bg-surface);
  display: flex; flex-direction: column;
  position: relative; overflow: hidden;
  border-left: 1px solid var(--border-subtle);
}

.resize-handle {
  position: absolute; left: -5px; top: 0; bottom: 0;
  width: 10px; cursor: col-resize; z-index: 10;
  display: flex; align-items: center; justify-content: center;
  transition: background var(--spring-fast);
}

.resize-handle:hover { background: var(--accent-dim); }

.resize-handle-line {
  width: 2px; height: 24px; border-radius: 1px;
  background: var(--border); transition: all var(--spring-medium);
}

.resize-handle:hover .resize-handle-line {
  height: 36px; background: var(--accent);
}

.chat-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 18px; flex-shrink: 0;
}

.chat-header-title {
  font-size: 14px; font-weight: 600;
  color: var(--text-primary);
  font-family: 'Noto Serif SC', serif;
}

.chat-clear-btn {
  background: none; border: none;
  color: var(--text-muted); padding: 4px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--spring-fast);
}

.chat-clear-btn:hover { color: var(--rose); background: var(--rose-dim); }

.chat-msgs {
  flex: 1; overflow-y: auto;
  padding: 16px 20px;
  display: flex; flex-direction: column; gap: 20px;
}

.chat-msgs::-webkit-scrollbar { width: 4px; }
.chat-msgs::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 2px; }
.chat-msgs::-webkit-scrollbar-thumb:hover { background: var(--scrollbar-thumb-hover); }

.chat-welcome {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 30px 16px 24px; text-align: center; gap: 4px;
}

.chat-welcome-icon {
  width: 56px; height: 56px; border-radius: 50%;
  background: var(--accent); display: flex; align-items: center; justify-content: center;
  color: var(--accent-on); margin-bottom: 12px;
  box-shadow: 0 2px 16px rgba(var(--accent-rgb), 0.15);
}

.chat-welcome-text {
  font-size: 16px; font-weight: 600; color: var(--text-primary);
  font-family: 'Noto Serif SC', serif;
}

.chat-welcome-sub {
  font-size: 13px; color: var(--text-muted); line-height: 1.6; margin-bottom: 16px;
}

.chat-suggestions {
  display: flex; flex-wrap: wrap; gap: 8px; justify-content: center;
}

.chat-suggestion {
  padding: 7px 16px; border-radius: 18px;
  border: 1px solid var(--border); background: var(--bg-raised);
  color: var(--text-secondary); font-size: 13px;
  transition: all var(--spring-fast); font-weight: 500; white-space: nowrap;
}

.chat-suggestion:hover {
  border-color: var(--accent); color: var(--accent);
  background: var(--accent-dim); transform: translateY(-1px);
}

.msg {
  display: flex; gap: 10px; max-width: 100%;
  animation: msg-in 300ms var(--spring-medium) both;
}

.msg.user { flex-direction: row-reverse; }

.msg-avatar {
  width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; font-family: 'Noto Serif SC', serif;
}

.msg.user .msg-avatar { background: var(--accent-soft); color: var(--accent); }
.msg.agent .msg-avatar { background: var(--accent); color: var(--accent-on); }

.msg-body { max-width: calc(100% - 46px); }

.msg-name {
  font-size: 11px; color: var(--text-muted); margin-bottom: 4px;
  padding: 0 2px;
}

.msg.user .msg-name { text-align: right; }

.msg-bubble {
  padding: 10px 14px; border-radius: 14px;
  font-size: 14px; line-height: 1.7; word-break: break-word;
}

.msg.user .msg-bubble {
  background: var(--accent); color: var(--accent-on); border-bottom-right-radius: 4px;
  font-weight: 500;
}

.msg-text { white-space: pre-wrap; }

.msg.agent .msg-bubble {
  background: var(--bg-raised); color: var(--text-secondary);
  border: 1px solid var(--border); border-bottom-left-radius: 4px;
}

.chat-md :deep(h1), .chat-md :deep(h2), .chat-md :deep(h3) {
  color: var(--text-primary); margin: 0.6em 0 0.3em; font-weight: 600;
  font-family: 'Noto Serif SC', serif;
}

.chat-md :deep(h1) { font-size: 1.15em; }
.chat-md :deep(h2) { font-size: 1.05em; }
.chat-md :deep(h3) { font-size: 0.95em; }
.chat-md :deep(p) { margin: 0.3em 0; }
.chat-md :deep(strong) { color: var(--text-primary); font-weight: 600; }
.chat-md :deep(code) { background: var(--bg-input); padding: 2px 6px; border-radius: 4px; font-size: 0.88em; font-family: 'JetBrains Mono', monospace; }
.chat-md :deep(pre) { background: var(--bg-input); padding: 10px 14px; border-radius: 8px; overflow-x: auto; margin: 0.5em 0; }
.chat-md :deep(pre code) { background: none; padding: 0; }
.chat-md :deep(blockquote) { border-left: 3px solid var(--accent); padding-left: 10px; margin: 0.4em 0; color: var(--text-muted); }
.chat-md :deep(ul), .chat-md :deep(ol) { padding-left: 1.4em; margin: 0.3em 0; }
.chat-md :deep(li) { margin: 0.15em 0; }
.chat-md :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 0.6em 0; }
.chat-md :deep(a) { color: var(--accent); }

.streaming-content .streaming-cursor {
  display: inline-block; width: 2px; height: 1em;
  background: var(--accent); margin-left: 1px;
  vertical-align: text-bottom;
  animation: cursor-blink 0.8s step-end infinite;
}

.thinking-block {
  margin-bottom: 8px; border-radius: 10px;
  border: 1px solid var(--border); overflow: hidden;
}

.thinking-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; font-size: 13px;
  color: var(--text-muted); cursor: pointer; user-select: none;
  transition: background var(--spring-fast);
}

.thinking-header:hover { background: var(--bg-hover); }

.thinking-dots { display: flex; gap: 3px; }

.thinking-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--accent);
  animation: dot-pulse 1.4s ease-in-out infinite;
}

.thinking-toggle { margin-left: auto; font-size: 10px; opacity: 0.5; }

.thinking-body {
  padding: 10px 14px; font-size: 12px; line-height: 1.6;
  color: var(--text-muted); white-space: pre-wrap; word-break: break-word;
  max-height: 160px; overflow-y: auto;
  border-top: 1px solid var(--border);
  background: var(--bg-input);
  font-family: 'JetBrains Mono', monospace;
}

.thinking-body::-webkit-scrollbar { width: 3px; }
.thinking-body::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 2px; }

.activity-block .thinking-header { font-size: 12px; color: var(--text-faint); }

.activity-list {
  list-style: none; margin: 0; padding: 8px 14px 10px;
  border-top: 1px solid var(--border);
  background: var(--bg-input);
}

.activity-item {
  display: flex; align-items: flex-start; gap: 8px;
  font-size: 12px; line-height: 1.5; color: var(--text-muted);
  padding: 2px 0;
}

.activity-status {
  flex-shrink: 0; font-size: 8px; line-height: 1.8;
  color: var(--text-faint);
}

.activity-status.running { color: var(--accent); animation: dot-pulse 1.4s ease-in-out infinite; }
.activity-status.done { color: #6b9e7a; }
.activity-status.error { color: #c96b6b; }

.chat-input-area { padding: 12px 16px 16px; flex-shrink: 0; position: relative; }

.mention-menu {
  position: absolute;
  bottom: 100%;
  left: 16px; right: 16px;
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-raised);
  max-height: 280px;
  overflow-y: auto;
  z-index: 10;
  margin-bottom: 4px;
}

.mention-menu-header {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-faint);
  padding: 8px 12px 4px;
  border-bottom: 1px solid var(--border-subtle);
}

.mention-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 12px;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background var(--spring-fast);
}

.mention-item:hover, .mention-item.active { background: var(--accent-dim); }

.mention-item-icon {
  width: 20px; height: 20px;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px;
  color: var(--accent);
}

.mention-item-label {
  flex: 1;
  font-size: 12.5px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mention-item-type {
  font-size: 10px;
  color: var(--text-faint);
  font-family: 'JetBrains Mono', monospace;
}

.mentions-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 10px 0;
}

.mention-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--accent-dim);
  border: 1px solid rgba(var(--accent-rgb), 0.2);
  border-radius: 10px;
  font-size: 11px;
  color: var(--accent);
}

.mention-chip-x {
  border: none;
  background: none;
  color: var(--accent);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  padding: 0;
  opacity: 0.6;
}

.mention-chip-x:hover { opacity: 1; }

.chat-input-wrap.has-mentions { padding-top: 4px; }

.chat-input-wrap {
  display: flex; align-items: flex-end; gap: 0;
  background: var(--bg-input); border: 1px solid var(--border);
  border-radius: 16px; padding: 6px 6px 6px 16px;
  transition: all var(--spring-fast);
}

.chat-input-wrap:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim);
}

.chat-input {
  flex: 1; padding: 7px 0;
  border: none; background: transparent;
  color: var(--text-primary); font-size: 14px;
  outline: none; resize: none;
  line-height: 1.5; max-height: 120px;
  caret-color: var(--accent);
  font-family: inherit;
}

.chat-input::placeholder { color: var(--text-faint); }

.chat-send-btn {
  width: 34px; height: 34px; border: none; border-radius: 50%;
  background: var(--accent); color: var(--accent-on);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: all var(--spring-fast);
  box-shadow: 0 1px 6px rgba(var(--accent-rgb), 0.2);
}

.chat-send-btn:hover { transform: scale(1.06); }
.chat-send-btn:active { transform: scale(0.94); }

.chat-stop-btn {
  width: 34px; height: 34px; border: none; border-radius: 50%;
  background: var(--rose); color: #fff;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: all var(--spring-fast);
  box-shadow: 0 1px 6px rgba(var(--rose-rgb), 0.2);
}

.chat-stop-btn:hover { transform: scale(1.06); }
.chat-stop-btn:active { transform: scale(0.94); }
</style>
