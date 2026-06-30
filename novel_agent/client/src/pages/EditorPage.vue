<template>
  <div class="editor-layout">
    <header class="header">
      <button class="btn btn-ghost" @click="goHome" title="返回" aria-label="返回书库">
        <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3 8l5-5 5 5" /><path d="M5 6v6h6V6" />
        </svg>
        书库
      </button>
      <div class="header-title">
        <span class="header-book-name">{{ editorStore.currentBookName || '墨灵' }}</span>
      </div>
      <div class="header-actions">
        <button
          class="btn btn-sync"
          :class="{ 'has-pending': syncStatus?.has_pending }"
          :disabled="syncing || !syncStatus?.has_pending"
          title="将近期章节沉淀进章摘要、角色、地点、关系、伏笔与写作设定（不改未来细纲）"
          @click="openSyncConfirm"
        >
          同步设定
          <span v-if="syncStatus?.has_pending && syncStatus.pending_chapters > 0" class="sync-badge">
            {{ syncStatus.pending_chapters }}
          </span>
        </button>
        <button class="sidebar-toggle" @click="editorStore.toggleSidebar()" title="切换侧边栏 (Ctrl+\\)" aria-label="切换侧边栏">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
            <line x1="2" y1="4" x2="14" y2="4" /><line x1="2" y1="8" x2="14" y2="8" /><line x1="2" y1="12" x2="14" y2="12" />
          </svg>
        </button>
      </div>
    </header>

    <div v-if="showSyncBanner" class="sync-banner">
      <span>
        有 {{ syncStatus?.pending_chapters }} 章尚未同步到设定（第 {{ syncStatus?.chapter_from }}–{{ syncStatus?.chapter_to }} 章）
      </span>
      <div class="sync-banner-actions">
        <button class="btn btn-sync-inline" @click="openSyncConfirm">立即同步</button>
        <button class="btn btn-ghost" @click="dismissSyncBanner">今天不再提醒</button>
      </div>
    </div>

    <div class="main" :class="{ 'sidebar-hidden': !editorStore.sidebarVisible }">
      <SideBar @field-changed="onFieldChanged" @gen-field="onGenField" />

      <div class="chapter-view" :class="{ 'has-editor': !!editorStore.editingField }">
        <template v-if="!editorStore.editingField">
          <div v-if="lastWrittenChapter" class="chapter-doc">
            <h2>第 {{ lastWrittenChapter.idx }} 章 · {{ lastWrittenChapter.title }}</h2>
            <div class="ch-summary-line">{{ lastWrittenChapter.content_summary || '' }}</div>
            <p class="ch-hint">点击侧边栏中的章节可查看完整内容。</p>
          </div>
          <div v-else-if="nextChapter" class="chapter-placeholder">
            <div class="ph-ornament">
              <svg width="24" height="24" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="0.9" stroke-linecap="round" stroke-linejoin="round">
                <path d="M11 2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z" /><polyline points="8,6 8,10" /><line x1="6" y1="8" x2="10" y2="8" />
              </svg>
            </div>
            <h3>{{ nextChapter.title }}</h3>
            <p>{{ nextChapter.content_summary || '输入「续写」开始创作。' }}</p>
          </div>
          <div v-else class="chapter-placeholder">
            <div class="ph-ornament">
              <svg width="24" height="24" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="0.9" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 2v12l5-3 5 3V2a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1z" />
              </svg>
            </div>
            <h3>墨灵</h3>
            <p>AI 辅助修仙小说创作。生成大纲、续写章节、管理伏笔、雕琢角色——尽在一个编辑器中。</p>
          </div>
        </template>

        <MarkdownEditor
          v-else
          :title="editorPanelTitle"
          :content="editorPanelContent"
          :chapter-title="chapterTitle"
          :show-chapter-title="isChapterView"
          :show-mode-btns="!isTitleField"
          :preview-mode="isTitleField ? false : editorStore.mdPreviewMode"
          :generating="editorStore.isGenerating"
          :saving="saving"
          :streaming="isStreamingToField"
          :can-undo="canUndo"
          :can-redo="canRedo"
          :highlights="editorStore.fieldHighlights[editorStore.editingField]"
          :pre-edit-content="editorStore.preEditContent[editorStore.editingField]"
          :placeholder="isChapterView ? '撰写章节内容...' : undefined"
          @update:content="onContentInput"
          @update:chapter-title="chapterTitle = $event"
          @save="onEditorSave"
          @stop="editorStore.stopGeneration()"
          @switch-mode="editorStore.mdPreviewMode = $event === 'preview'"
          @undo="doUndo"
          @redo="doRedo"
          @update-highlights="onUpdateHighlights"
        />
      </div>

      <ChatPanel
        :confirm-unsaved="confirmUnsavedBeforeAction"
        :save-current="doSaveCurrent"
        :handle-event="handleEvent"
      />
    </div>

    <Teleport to="body">
      <div v-if="showSyncModal" class="modal-overlay" @click.self="!syncing && (showSyncModal = false)" @keydown.esc="!syncing && (showSyncModal = false)" tabindex="-1">
        <div class="modal modal-wide">
          <div class="modal-eyebrow">设定维护</div>
          <h3>{{ syncing ? '正在同步设定…' : '同步设定' }}</h3>
          <p v-if="!syncing" class="modal-desc">
            将根据第 {{ syncStatus?.chapter_from }}–{{ syncStatus?.chapter_to }} 章更新：
            章节摘要、角色、地点、关系、伏笔、写作设定。<strong>不会修改未来细纲。</strong>
          </p>
          <pre v-if="syncLog" class="sync-log">{{ syncLog }}</pre>
          <div class="modal-actions">
            <button class="modal-btn modal-btn-cancel" :disabled="syncing" @click="showSyncModal = false">取消</button>
            <button v-if="!syncing" class="modal-btn modal-btn-confirm" @click="runDailySync">开始同步</button>
          </div>
        </div>
      </div>

      <div v-if="showUnsavedModal" class="modal-overlay" @click.self="resolveUnsavedAction('cancel')" @keydown.esc="resolveUnsavedAction('cancel')" tabindex="-1">
        <div class="modal">
          <div class="modal-eyebrow">未保存的修改</div>
          <h3>{{ unsavedModalTitle }}</h3>
          <p class="modal-desc">{{ unsavedModalDesc }}</p>
          <div class="modal-actions">
            <button class="modal-btn modal-btn-cancel" @click="resolveUnsavedAction('cancel')">取消</button>
            <button class="modal-btn modal-btn-ghost" @click="resolveUnsavedAction('discard')">不保存</button>
            <button class="modal-btn modal-btn-confirm" @click="resolveUnsavedAction('save')">保存</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useEditorStore, useChatStore, useConfirmStore } from '@/stores'
import { FIELD_TITLES, PLACEHOLDER_DEFAULTS } from '@/types'
import type { SseEvent, DailySyncStatus } from '@/types'
import * as api from '@/api'
import SideBar from '@/components/SideBar.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import { createSseHandler, consumeStream } from '@/composables/useSseHandler'
import { useUnsavedConfirm } from '@/composables/useUnsavedConfirm'
import { useAutoSave } from '@/composables/useAutoSave'

const router = useRouter()
const editorStore = useEditorStore()
const chatStore = useChatStore()
const confirmStore = useConfirmStore()

const saving = ref(false)
const syncing = ref(false)
const syncStatus = ref<DailySyncStatus | null>(null)
const showSyncBanner = ref(false)
const showSyncModal = ref(false)
const syncLog = ref('')

const {
  showUnsavedModal, unsavedModalTitle, unsavedModalDesc,
  confirmUnsavedBeforeAction, resolveUnsavedAction,
} = useUnsavedConfirm()

const titleValue = ref('')
const chapterTitle = ref('')

let _fieldLoadGuard = false

const isTitleField = computed(() => editorStore.editingField === 'title')
const isChapterView = computed(() =>
  editorStore.editingField === 'chapter_new' || editorStore.isChapterField(editorStore.editingField),
)
const isStreamingToField = computed(() =>
  editorStore.isGenerating
  && !!editorStore.generatingTarget
  && editorStore.editingField === editorStore.generatingTarget,
)
const editorPanelTitle = computed(() => {
  if (isTitleField.value) return '小说标题'
  if (editorStore.editingField === 'chapter_new') return '新建章节'
  if (editorStore.isChapterField(editorStore.editingField)) {
    return '第' + editorStore.getChapterIdx() + '章'
  }
  return fieldTitle.value
})
const editorPanelContent = computed(() => getCurrentContent())

const fieldTitle = computed(() => {
  return FIELD_TITLES[editorStore.editingField] || editorStore.editingField
})

const canUndo = computed(() => editorStore.canUndoGeneration())
const canRedo = computed(() => editorStore.canRedoGeneration())

const lastWrittenChapter = computed(() => {
  const written = editorStore.chapters.filter(ch => ch.is_written)
  return written.length ? written[written.length - 1] : null
})

const nextChapter = computed(() => {
  const next = editorStore.chapters.find(ch => !ch.is_written && (ch.title || ch.content_summary))
  return next || null
})

function goHome() {
  router.push('/')
}

async function loadSyncStatus() {
  try {
    syncStatus.value = await api.getDailySyncStatus()
    showSyncBanner.value = !!syncStatus.value?.should_prompt
  } catch {
    syncStatus.value = null
    showSyncBanner.value = false
  }
}

function openSyncConfirm() {
  if (!syncStatus.value?.has_pending) return
  syncLog.value = ''
  showSyncModal.value = true
}

async function dismissSyncBanner() {
  try {
    const res = await api.dismissDailySyncPrompt()
    syncStatus.value = res.status
    showSyncBanner.value = false
  } catch { /* ignore */ }
}

const syncHandleEvent = createSseHandler(chatStore, editorStore, {
  collapseThinkingOnToken: false,
  onError: (evt) => { syncLog.value += `\n出错了：${evt.error || '未知错误'}\n` },
})

async function runDailySync() {
  if (syncing.value) return
  syncing.value = true
  syncLog.value = ''
  try {
    for await (const evt of api.dailySyncStream()) {
      syncHandleEvent(evt)
      if (evt.type === 'token') syncLog.value += evt.token || ''
      if (evt.type === 'daily_sync_done') {
        syncLog.value += '\n✅ 设定同步完成\n'
      }
      if (evt.type === 'error') {
        syncLog.value += `\n❌ ${evt.error}\n`
        break
      }
    }
    await loadSyncStatus()
  } catch (e: any) {
    syncLog.value += `\n❌ ${e.message || '同步失败'}\n`
  } finally {
    syncing.value = false
  }
}

async function onFieldChanged() {
  const field = editorStore.editingField
  if (_inputDebounceTimer) { clearTimeout(_inputDebounceTimer); _inputDebounceTimer = null }
  _editBaseSnapshot = null
  _fieldLoadGuard = true
  if (field === 'title') {
    titleValue.value = editorStore.currentState?.meta?.title || ''
  } else if (field === 'chapter_new') {
    chapterTitle.value = editorStore.pendingChapterTitle || chapterTitle.value || nextChapter.value?.title || ''
    const resumingGeneration =
      editorStore.isGenerating && editorStore.generatingTarget === 'chapter_new'
    if (!resumingGeneration) {
      editorStore.streamingChapterContent = ''
    }
  } else if (editorStore.isChapterField(field)) {
    const onGeneratingTarget =
      editorStore.isGenerating && field === editorStore.generatingTarget
    if (onGeneratingTarget) {
      chapterTitle.value = editorStore.pendingChapterTitle || chapterTitle.value || ''
    } else {
      const idx = editorStore.getChapterIdx()
      if (idx) {
        try {
          editorStore.activeChapterIdx = idx
          const data = await api.getChapterContent(idx)
          chapterTitle.value = data.title || ''
          editorStore.streamingChapterContent = data.content || ''
        } catch { /* ignore */ }
      }
    }
  } else {
    const raw = editorStore.fieldValues[field] || ''
    editorStore.streamingFieldContent = PLACEHOLDER_DEFAULTS.includes(raw) ? '' : raw
  }
  void loadSyncStatus()
  nextTick(() => { _fieldLoadGuard = false })
}

async function saveTitle() {
  saving.value = true
  try {
    await editorStore.saveFieldEdit('title', titleValue.value)
    editorStore.resetDirty()
  } finally {
    saving.value = false
  }
}

async function saveChapterEdit() {
  const idx = editorStore.getChapterIdx()
  if (!idx) return
  if (!chapterTitle.value.trim()) return
  saving.value = true
  try {
    await editorStore.saveChapterEdit(idx, chapterTitle.value.trim(), getCurrentContent())
    editorStore.resetDirty()
    await loadSyncStatus()
  } finally {
    saving.value = false
  }
}

async function saveNewChapter() {
  if (!chapterTitle.value.trim()) return
  saving.value = true
  try {
    await editorStore.saveNewChapter(chapterTitle.value.trim(), getCurrentContent())
    editorStore.resetDirty()
    await loadSyncStatus()
  } finally {
    saving.value = false
  }
}

async function saveFieldEdit() {
  saving.value = true
  try {
    await editorStore.saveFieldEdit(editorStore.editingField, editorStore.streamingFieldContent)
    editorStore.fieldValues[editorStore.editingField] = editorStore.streamingFieldContent
    editorStore.resetDirty()
  } finally {
    saving.value = false
  }
}

async function onEditorSave() {
  const field = editorStore.editingField
  if (field === 'title') await saveTitle()
  else if (field === 'chapter_new') await saveNewChapter()
  else if (editorStore.isChapterField(field)) await saveChapterEdit()
  else if (field) await saveFieldEdit()
}

function onUpdateHighlights(highlights: number[]) {
  const f = editorStore.editingField
  if (!f) return
  if (highlights.length === 0) {
    delete editorStore.fieldHighlights[f]
  } else {
    editorStore.fieldHighlights[f] = highlights
  }
}

async function doSaveCurrent(isAuto: boolean = false) {
  const field = editorStore.editingField
  // continue_writing 已在后端落盘，避免自动保存重复新建章节
  if (isAuto && field === 'chapter_new') return
  if (field === 'chapter_new') await saveNewChapter()
  else if (editorStore.isChapterField(field)) await saveChapterEdit()
  else if (field === 'title') await saveTitle()
  else if (field) await saveFieldEdit()
}

const {
  startGeneratedSaveTimer: _startGeneratedSaveTimer,
  stopGeneratedSaveTimer: _stopGeneratedSaveTimer,
  startAutoSave,
  stopAutoSave,
} = useAutoSave(doSaveCurrent)

async function onGenField(field: string) {
  if (editorStore.isGenerating) return
  editorStore.editingField = field
  editorStore.mdPreviewMode = false
  onFieldChanged()
  const message =
    field === 'outline_future_md_content' ? '生成未来大纲' : `生成${FIELD_TITLES[field as keyof typeof FIELD_TITLES] || field}`
  chatStore.addUserMessage(message)
  chatStore.streamingContent = ''
  chatStore.reasoningContent = ''
  chatStore.showThinking = false
  chatStore.thinkingCollapsed = false
  editorStore.startGeneration()
  const stream = api.chatStream(message, editorStore.fieldValues, editorStore.abortController?.signal)
  await consumeStream(stream, {
    chatStore, editorStore, handleEvent,
    onSuccess: _startGeneratedSaveTimer,
  })
}

function getCurrentContent(): string {
  const field = editorStore.editingField
  if (!field) return ''
  if (editorStore.isGenerating && field === editorStore.generatingTarget) {
    return editorStore.generatingStreamContent
  }
  if (field === 'chapter_new' || editorStore.isChapterField(field)) return editorStore.streamingChapterContent
  if (field === 'title') return titleValue.value
  return editorStore.streamingFieldContent
}

function setCurrentContent(value: string) {
  const field = editorStore.editingField
  if (!field) return
  if (editorStore.isGenerating && field === editorStore.generatingTarget) {
    editorStore.generatingStreamContent = value
    return
  }
  if (field === 'chapter_new' || editorStore.isChapterField(field)) {
    editorStore.streamingChapterContent = value
  } else if (field === 'title') {
    titleValue.value = value
  } else {
    editorStore.streamingFieldContent = value
  }
}

function getCurrentTitle(): string {
  const field = editorStore.editingField
  if (field === 'chapter_new' || editorStore.isChapterField(field)) return chapterTitle.value
  return ''
}

let _inputDebounceTimer: ReturnType<typeof setTimeout> | null = null
let _editBaseSnapshot: { content: string; title: string } | null = null

function onContentInput(newValue: string) {
  const field = editorStore.editingField
  if (!field) return

  if (_fieldLoadGuard) {
    setCurrentContent(newValue)
    return
  }

  if (!_editBaseSnapshot) {
    _editBaseSnapshot = { content: getCurrentContent(), title: getCurrentTitle() }
  }

  setCurrentContent(newValue)
  editorStore.markDirty()

  if (_inputDebounceTimer) clearTimeout(_inputDebounceTimer)
  _inputDebounceTimer = setTimeout(flushManualSnapshot, 600)
}

function flushManualSnapshot() {
  _inputDebounceTimer = null
  if (!_editBaseSnapshot) return
  const field = editorStore.editingField
  if (!field) { _editBaseSnapshot = null; return }

  const baseContent = _editBaseSnapshot.content
  const baseTitle = _editBaseSnapshot.title
  const curContent = getCurrentContent()
  const curTitle = getCurrentTitle()

  if (baseContent !== curContent || baseTitle !== curTitle) {
    editorStore.pushContentSnapshot('编辑前', baseContent, baseTitle)
    editorStore.pushContentSnapshot('编辑后', curContent, curTitle)
  }
  _editBaseSnapshot = null
}

function applySnapshot(snapshot: { field: string; content: string; title: string }) {
  _fieldLoadGuard = true
  if (editorStore.isChapterField(snapshot.field) || snapshot.field === 'chapter_new') {
    chapterTitle.value = snapshot.title || ''
    editorStore.streamingChapterContent = snapshot.content || ''
  } else if (snapshot.field === 'title') {
    titleValue.value = snapshot.content || ''
  } else {
    editorStore.streamingFieldContent = snapshot.content || ''
  }
  nextTick(() => { _fieldLoadGuard = false })
}

async function doUndo() {
  _stopGeneratedSaveTimer()
  flushManualSnapshot()
  const snapshot = editorStore.undoGeneration()
  if (snapshot) {
    applySnapshot(snapshot)
    editorStore.resetDirty()
    await doSaveCurrent()
  }
}

async function doRedo() {
  _stopGeneratedSaveTimer()
  flushManualSnapshot()
  const snapshot = editorStore.redoGeneration()
  if (snapshot) {
    applySnapshot(snapshot)
    editorStore.resetDirty()
    await doSaveCurrent()
  }
}

const handleEvent = createSseHandler(chatStore, editorStore, {
  collapseThinkingOnToken: false,
  onError: (evt) => { chatStore.addAgentMessage('出错了：' + (evt.error || '未知错误')) },
  onChapterTitle: (title) => { chapterTitle.value = title },
  onGenerateDone: () => {
    editorStore.pushContentSnapshot('生成后', getCurrentContent(), getCurrentTitle())
  },
  onInterrupt: (evt) => handleInterrupt(evt),
})

async function handleInterrupt(evt: SseEvent) {
  if (evt.type !== 'interrupt') return
  const msg = evt.interrupt.message || 'Agent 需要你的确认才能继续'
  const ok = await confirmStore.confirm({
    title: '需要确认',
    desc: msg + '\n\n点击"确认"继续，点击"取消"跳过',
    confirmText: '继续',
    cancelText: '跳过',
  })

  editorStore.startGeneration()
  chatStore.streamingContent = ''
  chatStore.streamingActivity = []
  chatStore.reasoningContent = ''
  chatStore.showThinking = false
  chatStore.thinkingCollapsed = false

  const stream = api.resumeStream(ok, editorStore.abortController?.signal)
  await consumeStream(stream, {
    chatStore, editorStore, handleEvent,
    includeThinking: true,
    onSuccess: _startGeneratedSaveTimer,
  })
}

onMounted(async () => {
  try {
    await editorStore.fetchState()
    await loadSyncStatus()
    if (editorStore.currentState?.has_outline) { editorStore.editingField = 'outline_future_md_content'; onFieldChanged() }
    await chatStore.loadHistory()
    startAutoSave()
  } catch (e) { console.error('初始化失败:', e) }
  window.addEventListener('keydown', onGlobalKeydown)
})

onBeforeUnmount(() => {
  stopAutoSave()
  _stopGeneratedSaveTimer()
  editorStore.fieldHighlights = {}
  editorStore.preEditContent = {}
  window.removeEventListener('keydown', onGlobalKeydown)
})

function onGlobalKeydown(e: KeyboardEvent) {
  if (e.defaultPrevented) return
  const mod = e.ctrlKey || e.metaKey
  const target = e.target as HTMLElement | null
  const inEditable = !!target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)

  if (mod && e.key.toLowerCase() === 's') {
    e.preventDefault()
    void doSaveCurrent()
    return
  }

  if (mod && e.key === '\\') {
    e.preventDefault()
    editorStore.toggleSidebar()
    return
  }

  if (e.key === 'Escape' && !inEditable && editorStore.editingField) {
    e.preventDefault()
    editorStore.mdPreviewMode = !editorStore.mdPreviewMode
  }
}

watch([chapterTitle, () => editorStore.streamingChapterContent, () => editorStore.streamingFieldContent, titleValue], () => {
  if (_fieldLoadGuard) return
  if (editorStore.editingField && !editorStore.isGenerating) editorStore.markDirty()
})

watch(
  () => [editorStore.editingField, editorStore.pendingChapterTitle] as const,
  ([field, pending]) => {
    if (field === 'chapter_new' && pending) {
      chapterTitle.value = pending
    }
  },
)

watch(() => editorStore.editingField, (field, oldField) => {
  if (!field || field === oldField) return
  if (!editorStore.isGenerating || editorStore.viewPinned) {
    onFieldChanged()
  } else if (field === 'chapter_new') {
    chapterTitle.value = editorStore.pendingChapterTitle || chapterTitle.value
  }
})

watch(() => ({ ...editorStore.fieldValues }), () => {
  if (!editorStore.isGenerating) return
  const f = editorStore.editingField
  if (!f || f === editorStore.generatingTarget) return
  if (editorStore.isChapterField(f) || f === 'chapter_new') {
    editorStore.streamingChapterContent = editorStore.fieldValues[f] || editorStore.streamingChapterContent
  } else if (f === 'title') {
    titleValue.value = editorStore.fieldValues[f] || titleValue.value
  } else if (f) {
    editorStore.streamingFieldContent = editorStore.fieldValues[f] || editorStore.streamingFieldContent
  }
}, { deep: true })

watch(() => editorStore.sidebarVisible, (visible) => {
  const mainEl = document.querySelector('.main') as HTMLElement
  if (!mainEl) return
  const cols = mainEl.style.gridTemplateColumns.split(' ')
  const chatCol = cols.length === 3 ? cols[2] : '1fr'
  const col1 = visible ? 'var(--sidebar-w)' : '0'
  mainEl.style.gridTemplateColumns = col1 + ' 1fr ' + chatCol
})
</script>

<style scoped>
.editor-layout { height: 100dvh; display: grid; grid-template-rows: var(--header-h) auto 1fr; overflow: hidden; }

.header {
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 18px;
  gap: 16px;
  z-index: 20;
  position: relative;
}

.header-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  letter-spacing: 0.01em;
}

.header-book-name { color: var(--text-primary); }

.header-actions { margin-left: auto; display: flex; gap: 6px; }

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  font-size: 12.5px;
  font-weight: 500;
  font-family: inherit;
  transition: all var(--spring-fast);
}

.btn:hover { background: var(--bg-hover); border-color: var(--border); color: var(--text-secondary); }
.btn:active { transform: scale(0.97); }
.btn-ghost { border-color: transparent; }
.btn-ghost:hover { background: var(--bg-hover); }

.btn-sync {
  position: relative;
  border-color: var(--border);
  color: var(--text-secondary);
  background: var(--bg-surface);
}

.btn-sync:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-dim);
}

.btn-sync:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-sync.has-pending:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}

.sync-badge {
  margin-left: 6px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--accent);
  color: var(--accent-on);
  font-size: 10px;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
}

.sync-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 18px;
  background: var(--accent-dim);
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--text-secondary);
}

.sync-banner-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.btn-sync-inline {
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  border: none;
  background: var(--accent);
  color: var(--accent-on);
  font-size: 12px;
  font-weight: 600;
}

.sync-log {
  max-height: 240px;
  overflow: auto;
  margin: 0 0 16px;
  padding: 12px 14px;
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.sidebar-toggle {
  width: 34px; height: 34px;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--border-subtle); border-radius: var(--radius-sm);
  background: transparent; color: var(--text-muted);
  transition: all var(--spring-fast); flex-shrink: 0;
}

.sidebar-toggle:hover { background: var(--bg-hover); color: var(--text-secondary); border-color: var(--border); }

.main {
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr 1fr;
  grid-template-rows: 100%;
  overflow: hidden;
  position: relative;
  transition: grid-template-columns var(--spring-slow);
  z-index: 1;
}

.chapter-view {
  overflow-y: auto;
  padding: 52px 56px;
  position: relative;
  background: var(--bg-root);
}

.chapter-view.has-editor {
  display: flex; flex-direction: column;
  padding: 28px 36px; overflow: hidden; height: 100%;
}

.chapter-view::-webkit-scrollbar { width: 4px; }
.chapter-view::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
.chapter-view::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }

.chapter-placeholder {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 100%; max-width: 480px; margin: 0 auto; text-align: center;
  animation: reveal-up 700ms var(--spring-slow) both;
}

.ph-ornament {
  width: 60px; height: 60px;
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 24px; color: var(--accent);
  box-shadow: 0 0 40px rgba(var(--accent-rgb), 0.05);
}

.chapter-placeholder h3 {
  font-family: 'Noto Serif SC', serif;
  font-size: 24px; font-weight: 700;
  margin-bottom: 12px; color: var(--text-primary);
}

.chapter-placeholder p {
  font-size: 14px; color: var(--text-muted); line-height: 1.9;
  font-family: 'Noto Serif SC', serif;
}

.chapter-doc {
  max-width: 780px; margin: 0 auto; padding: 40px 0;
  animation: reveal-up 500ms var(--spring-slow) both;
}

.chapter-doc h2 {
  font-family: 'Noto Serif SC', serif;
  font-size: 28px; font-weight: 700; letter-spacing: -0.02em;
  color: var(--text-primary); margin-bottom: 14px;
}

.ch-summary-line {
  font-size: 14px; color: var(--accent); line-height: 1.8;
  margin-bottom: 20px; padding-left: 16px;
  border-left: 2px solid var(--accent);
  font-family: 'Noto Serif SC', serif;
}

.ch-hint {
  font-size: 13px; color: var(--text-faint); margin-top: 28px;
}

.modal-overlay {
  position: fixed; inset: 0;
  background: var(--overlay-bg); backdrop-filter: blur(6px);
  z-index: 100; display: flex; align-items: center; justify-content: center;
  animation: fade-in 180ms var(--spring-fast) both;
}

.modal {
  background: var(--bg-raised); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 28px 32px 22px;
  width: 440px; max-width: 92vw;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.7), 0 0 0 1px var(--border-subtle);
  animation: modal-in 350ms var(--spring-slow) both;
}

.modal-wide { width: 560px; }

.modal .modal-eyebrow {
  font-family: 'JetBrains Mono', monospace; font-size: 9.5px; font-weight: 500;
  letter-spacing: 0.18em; color: var(--accent); text-transform: uppercase; margin-bottom: 10px;
}

.modal h3 {
  font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 600;
  color: var(--text-primary); margin-bottom: 6px; letter-spacing: -0.02em;
}

.modal .modal-desc { font-size: 13px; color: var(--text-muted); margin-bottom: 22px; line-height: 1.6; }

.modal .modal-actions { display: flex; gap: 10px; justify-content: flex-end; }

.modal .modal-btn {
  padding: 10px 22px; border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 500; transition: all var(--spring-fast);
}

.modal .modal-btn-cancel { border: 1px solid var(--border); background: transparent; color: var(--text-muted); }
.modal .modal-btn-cancel:hover { background: var(--bg-hover); color: var(--text-secondary); border-color: var(--border-strong); }

.modal .modal-btn-confirm {
  border: none; background: var(--accent); color: var(--accent-on);
  font-weight: 600; border-radius: 24px;
}

.modal .modal-btn-confirm:hover { background: var(--accent-strong); transform: scale(1.02); }
.modal .modal-btn-confirm:active { transform: scale(0.97); }
.modal .modal-btn-confirm:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

.modal .modal-btn-ghost {
  border: 1px solid var(--border); background: transparent; color: var(--text-secondary);
}

.modal .modal-btn-ghost:hover { background: var(--bg-hover); border-color: var(--border-strong); }
</style>
