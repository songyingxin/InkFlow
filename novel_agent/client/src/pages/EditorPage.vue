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
        <button class="sidebar-toggle" @click="editorStore.toggleSidebar()" title="切换侧边栏 (Ctrl+\\)" aria-label="切换侧边栏">
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round">
            <line x1="2" y1="4" x2="14" y2="4" /><line x1="2" y1="8" x2="14" y2="8" /><line x1="2" y1="12" x2="14" y2="12" />
          </svg>
        </button>
      </div>
    </header>

    <div class="main" :class="{ 'sidebar-hidden': !editorStore.sidebarVisible }">
      <SideBar @show-import="showImportModal = true" @field-changed="onFieldChanged" @gen-field="onGenField" />

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

        <template v-else-if="editorStore.editingField === 'title'">
          <MarkdownEditor
            title="小说标题"
            :content="titleValue"
            :show-mode-btns="false"
            :generating="editorStore.isGenerating"
            :saving="saving"
            :can-undo="canUndo"
            :can-redo="canRedo"
            @update:content="onContentInput"
            @save="saveTitle"
            @stop="editorStore.stopGeneration()"
            @undo="doUndo"
            @redo="doRedo"
          />
        </template>

        <template v-else-if="editorStore.editingField === 'chapter_new'">
          <MarkdownEditor
            title="新建章节"
            :content="editorStore.streamingChapterContent"
            :chapter-title="chapterTitle"
            :show-chapter-title="true"
            :generating="editorStore.isGenerating"
            :saving="saving"
            :streaming="isStreamingToField"
            :can-undo="canUndo"
            :can-redo="canRedo"
            placeholder="撰写章节内容..."
            @update:content="onContentInput"
            @update:chapter-title="chapterTitle = $event"
            @save="saveNewChapter"
            @stop="editorStore.stopGeneration()"
            @switch-mode="editorStore.mdPreviewMode = $event === 'preview'"
            @undo="doUndo"
            @redo="doRedo"
          />
        </template>

        <template v-else-if="editorStore.isChapterField(editorStore.editingField)">
          <MarkdownEditor
            :title="'第' + editorStore.getChapterIdx() + '章'"
            :content="editorStore.streamingChapterContent"
            :chapter-title="chapterTitle"
            :show-chapter-title="true"
            :preview-mode="editorStore.mdPreviewMode"
            :generating="editorStore.isGenerating"
            :saving="saving"
            :streaming="isStreamingToField"
            :can-undo="canUndo"
            :can-redo="canRedo"
            :highlights="editorStore.fieldHighlights[editorStore.editingField]"
            :pre-edit-content="editorStore.preEditContent[editorStore.editingField]"
            placeholder="撰写章节内容..."
            @update:content="onContentInput"
            @update:chapter-title="chapterTitle = $event"
            @save="saveChapterEdit"
            @stop="editorStore.stopGeneration()"
            @switch-mode="editorStore.mdPreviewMode = $event === 'preview'"
            @undo="doUndo"
            @redo="doRedo"
            @update-highlights="onUpdateHighlights"
          />
        </template>

        <template v-else>
          <MarkdownEditor
            :title="fieldTitle"
            :content="editorStore.streamingFieldContent"
            :preview-mode="editorStore.mdPreviewMode"
            :generating="editorStore.isGenerating"
            :saving="saving"
            :streaming="isStreamingToField"
            :can-undo="canUndo"
            :can-redo="canRedo"
            :highlights="editorStore.fieldHighlights[editorStore.editingField]"
            :pre-edit-content="editorStore.preEditContent[editorStore.editingField]"
            @update:content="onContentInput"
            @save="saveFieldEdit"
            @stop="editorStore.stopGeneration()"
            @switch-mode="editorStore.mdPreviewMode = $event === 'preview'"
            @undo="doUndo"
            @redo="doRedo"
            @update-highlights="onUpdateHighlights"
          />
        </template>
      </div>

      <ChatPanel :confirm-unsaved="confirmUnsavedBeforeAction" :save-current="doSaveCurrent" />
    </div>

    <Teleport to="body">
      <div v-if="showImportModal" class="modal-overlay" @click.self="showImportModal = false" @keydown.esc="showImportModal = false" tabindex="-1">
        <div class="modal modal-wide">
          <div class="modal-eyebrow">导入</div>
          <h3>批量导入章节</h3>
          <p class="modal-desc">选择一个 JSON 文件，包含章节数组，每项需含 `title` 和 `content` 字段。</p>
          <div
            class="import-dropzone"
            :class="{ active: importDragActive }"
            @click="fileInputRef?.click()"
            @dragover.prevent="onDragOver"
            @dragleave="onDragLeave"
            @drop.prevent="onDrop"
          >
            <input ref="fileInputRef" type="file" accept=".json" style="display:none" @change="onFileChange" />
            <div class="import-dropzone-icon">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="12" y1="18" x2="12" y2="12" /><line x1="9" y1="15" x2="12" y2="12" /><line x1="15" y1="15" x2="12" y2="12" />
              </svg>
            </div>
            <p v-if="!importFile">{{ importDragActive ? '松开选择' : '点击或拖拽 JSON 文件到此处' }}</p>
            <p v-else class="import-file-name">{{ importFile.name }} ({{ (importFile.size / 1024).toFixed(1) }} KB)</p>
          </div>
          <div v-if="importPreview.length" class="import-preview">
            <div class="import-preview-title">预览：{{ importPreview.length }} 个章节</div>
            <div v-for="(ch, i) in importPreview.slice(0, 5)" :key="i" class="import-preview-item">{{ ch }}</div>
            <div v-if="importPreview.length > 5" class="import-preview-more">...还有 {{ importPreview.length - 5 }} 章</div>
          </div>
          <div v-if="importing" class="import-progress">
            <div class="import-progress-bar"><div class="import-progress-fill" :style="{ width: importProgress + '%' }" /></div>
            <p class="import-progress-text">{{ importProgressText }}</p>
          </div>
          <div class="modal-actions">
            <button class="modal-btn modal-btn-cancel" @click="showImportModal = false">取消</button>
            <button class="modal-btn modal-btn-confirm" :disabled="!importFile || importing" @click="confirmImport">
              {{ importing ? '导入中...' : '导入' }}
            </button>
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
import type { SseEvent } from '@/types'
import * as api from '@/api'
import SideBar from '@/components/SideBar.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import { createSseHandler, consumeStream } from '@/composables/useSseHandler'
import { useChapterImport } from '@/composables/useChapterImport'
import { useUnsavedConfirm } from '@/composables/useUnsavedConfirm'
import { useAutoSave } from '@/composables/useAutoSave'

const router = useRouter()
const editorStore = useEditorStore()
const chatStore = useChatStore()
const confirmStore = useConfirmStore()

const saving = ref(false)

const {
  showImportModal, importFile, importing, importProgress, importProgressText,
  importPreview, importDragActive, fileInputRef,
  onDragOver, onDragLeave, onDrop, onFileChange, confirmImport,
} = useChapterImport()

const {
  showUnsavedModal, unsavedModalTitle, unsavedModalDesc,
  confirmUnsavedBeforeAction, resolveUnsavedAction,
} = useUnsavedConfirm()

const titleValue = ref('')
const chapterTitle = ref('')
const isStreamingToField = ref(false)

let _fieldLoadGuard = false

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

async function onFieldChanged() {
  const field = editorStore.editingField
  if (_inputDebounceTimer) { clearTimeout(_inputDebounceTimer); _inputDebounceTimer = null }
  _editBaseSnapshot = null
  _fieldLoadGuard = true
  if (field === 'title') {
    titleValue.value = editorStore.currentState?.meta?.title || ''
  } else if (field === 'chapter_new') {
    chapterTitle.value = editorStore.pendingChapterTitle || ''
    editorStore.streamingChapterContent = ''
  } else if (editorStore.isChapterField(field)) {
    const idx = editorStore.getChapterIdx()
    if (idx) {
      try {
        const data = await editorStore.loadChapter(idx)
        chapterTitle.value = data.title || ''
        editorStore.streamingChapterContent = data.content || ''
      } catch { /* ignore */ }
    }
  } else {
    const raw = editorStore.fieldValues[field] || ''
    editorStore.streamingFieldContent = PLACEHOLDER_DEFAULTS.includes(raw) ? '' : raw
  }
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
    await editorStore.saveChapterEdit(idx, chapterTitle.value.trim(), editorStore.streamingChapterContent)
    editorStore.resetDirty()
  } finally {
    saving.value = false
  }
}

async function saveNewChapter() {
  if (!chapterTitle.value.trim()) return
  saving.value = true
  try {
    await editorStore.saveNewChapter(chapterTitle.value.trim(), editorStore.streamingChapterContent)
    editorStore.resetDirty()
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
  chatStore.addUserMessage('更新大纲')
  chatStore.streamingContent = ''
  chatStore.reasoningContent = ''
  chatStore.showThinking = false
  chatStore.thinkingCollapsed = false
  editorStore.startGeneration()
  const stream = api.chatStream('更新大纲', editorStore.fieldValues, editorStore.abortController?.signal)
  await consumeStream(stream, {
    chatStore, editorStore, handleEvent,
    onSuccess: _startGeneratedSaveTimer,
  })
}

function getCurrentContent(): string {
  const field = editorStore.editingField
  if (!field) return ''
  if (field === 'chapter_new' || editorStore.isChapterField(field)) return editorStore.streamingChapterContent
  if (field === 'title') return titleValue.value
  return editorStore.streamingFieldContent
}

function setCurrentContent(value: string) {
  const field = editorStore.editingField
  if (!field) return
  if (field === 'chapter_new' || editorStore.isChapterField(field)) editorStore.streamingChapterContent = value
  else if (field === 'title') titleValue.value = value
  else editorStore.streamingFieldContent = value
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
  onGenerateStart: () => { isStreamingToField.value = true },
  onGenerateDone: () => {
    isStreamingToField.value = false
    editorStore.pushContentSnapshot('生成后', getCurrentContent(), getCurrentTitle())
  },
  onGenerateReset: () => { isStreamingToField.value = false },
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
    if (editorStore.currentState?.has_outline) { editorStore.editingField = 'outline_historical_md_content'; onFieldChanged() }
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

watch(() => editorStore.editingField, (field, oldField) => {
  if (field && field !== oldField && !editorStore.isGenerating) {
    onFieldChanged()
  }
})

watch(() => ({ ...editorStore.fieldValues }), () => {
  if (!editorStore.isGenerating) return
  const f = editorStore.editingField
  if (!f) return
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
.editor-layout { height: 100dvh; display: grid; grid-template-rows: var(--header-h) 1fr; overflow: hidden; }

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

.import-dropzone {
  border: 2px dashed var(--border); border-radius: var(--radius-md);
  padding: 36px 24px; text-align: center; cursor: pointer;
  transition: all var(--spring-medium); margin-bottom: 20px;
}

.import-dropzone:hover, .import-dropzone.active { border-color: var(--accent); background: var(--accent-dim); }
.import-dropzone-icon { color: var(--text-muted); margin-bottom: 10px; opacity: 0.5; }
.import-dropzone p { font-size: 13px; color: var(--text-muted); margin: 0; }
.import-file-name { color: var(--accent) !important; font-weight: 500; }

.import-preview {
  margin-bottom: 18px; padding: 14px 16px;
  background: var(--bg-input); border-radius: var(--radius-md);
  border: 1px solid var(--border);
}

.import-preview-title {
  font-size: 12px; font-weight: 600; color: var(--text-secondary);
  margin-bottom: 8px;
}

.import-preview-item {
  font-size: 12px; color: var(--text-muted); padding: 3px 0;
  font-family: 'Noto Serif SC', serif;
}

.import-preview-more {
  font-size: 11px; color: var(--text-faint); padding: 4px 0;
}

.import-progress {
  margin-bottom: 18px; padding: 14px 16px;
  background: var(--bg-input); border-radius: var(--radius-md);
  border: 1px solid var(--border);
}

.import-progress-bar {
  height: 4px; background: var(--border); border-radius: 2px;
  overflow: hidden; margin-bottom: 8px;
}

.import-progress-fill {
  height: 100%; background: var(--accent); border-radius: 2px;
  transition: width var(--spring-medium);
}

.import-progress-text {
  font-size: 11.5px; color: var(--text-muted); margin: 0;
}
</style>
