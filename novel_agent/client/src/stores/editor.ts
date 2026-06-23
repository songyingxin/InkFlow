import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { charHighlightsToLineNumbers } from '@/utils/lineDiff'
import type { NovelState, ContentSnapshot } from '@/types'
import * as api from '@/api'

const FIELD_NAMES = [
  'settings_md_content',
  'outline_historical_md_content', 'outline_future_md_content',
  'characters_md_content', 'relationships_md_content', 'foreshadowing_md_content',
]

export const useEditorStore = defineStore('editor', () => {
  const currentState = ref<NovelState | null>(null)
  const activeChapterIdx = ref<number | null>(null)
  const editingField = ref('')
  const sidebarVisible = ref(true)
  const mdPreviewMode = ref(false)
  const fieldValues = ref<Record<string, string>>({})
  const isDirty = ref(false)
  const hasUnsavedGenerated = ref(false)
  const contentHistory = ref<ContentSnapshot[]>([])
  const historyIndex = ref(-1)
  const MAX_HISTORY = 20
  const isGenerating = ref(false)
  const abortController = ref<AbortController | null>(null)
  const pendingChapterTitle = ref('')
  const fieldHighlights = ref<Record<string, number[]>>({})
  const preEditContent = ref<Record<string, string>>({})
  const streamingFieldContent = ref('')
  const streamingChapterContent = ref('')

  const chapters = computed(() => currentState.value?.chapters || [])
  const currentBookName = computed(() => currentState.value?.current_book_name || '')
  const hasOutline = computed(() => currentState.value?.has_outline || false)

  function isChapterField(f: string) {
    return f && f.startsWith('chapter_')
  }

  function isNewChapter() {
    return editingField.value === 'chapter_new'
  }

  function getChapterIdx() {
    return isChapterField(editingField.value) ? parseInt(editingField.value.split('_')[1]) : null
  }

  function cleanPlaceholder(value: string) {
    if (!value) return ''
    const defaults = ['暂无大纲', '暂无历史大纲', '暂无未来大纲', '暂无设定', '暂无角色', '暂无关系图谱', '暂无伏笔']
    if (defaults.includes(value)) return ''
    return value
  }

  async function fetchState() {
    const data = await api.getState()
    currentState.value = data
    if (data.meta) {
      fieldValues.value.title = data.meta.title || ''
    }
    for (const f of FIELD_NAMES) {
      const v = (data as any)[f]
      if (v !== undefined && v !== null) {
        fieldValues.value[f] = typeof v === 'string' ? v : ''
      }
    }
  }

  async function loadChapter(idx: number) {
    const data = await api.getChapterContent(idx)
    activeChapterIdx.value = idx
    editingField.value = 'chapter_' + idx
    mdPreviewMode.value = false
    return data
  }

  async function saveChapterEdit(idx: number, title: string, content: string) {
    const data = await api.updateChapter(idx, title, content)
    currentState.value = data.state
    return data
  }

  async function saveNewChapter(title: string, content: string) {
    const data = await api.addChapter(title, content)
    currentState.value = data.state
    editingField.value = 'chapter_' + data.chapter.idx
    activeChapterIdx.value = data.chapter.idx
    return data
  }

  async function removeChapter(idx: number) {
    const data = await api.deleteChapter(idx)
    currentState.value = data.state
    if (activeChapterIdx.value === idx) {
      activeChapterIdx.value = null
      editingField.value = ''
    }
    return data
  }

  async function saveFieldEdit(field: string, value: string) {
    const data = await api.updateField(field, value)
    currentState.value = data.state
    return data
  }

  function startGeneration() {
    abortController.value = new AbortController()
    isGenerating.value = true
  }

  function stopGeneration() {
    if (abortController.value) {
      abortController.value.abort()
      abortController.value = null
    }
    isGenerating.value = false
  }

  function markDirty() { isDirty.value = true }
  function resetDirty() { isDirty.value = false; hasUnsavedGenerated.value = false }

  function pushContentSnapshot(label: string = '', content?: string, title?: string) {
    if (historyIndex.value < contentHistory.value.length - 1) {
      contentHistory.value = contentHistory.value.slice(0, historyIndex.value + 1)
    }
    const field = editingField.value
    contentHistory.value.push({
      field,
      chapterIdx: activeChapterIdx.value,
      title: title !== undefined
        ? title
        : (isChapterField(field)
          ? (currentState.value?.chapters?.find((c: any) => c.idx === activeChapterIdx.value)?.title || '')
          : ''),
      content: content !== undefined ? content : (fieldValues.value[field] || ''),
      label,
    })
    if (contentHistory.value.length > MAX_HISTORY) {
      contentHistory.value.shift()
    }
    historyIndex.value = contentHistory.value.length - 1
  }

  function canUndoGeneration(): boolean {
    for (let i = historyIndex.value - 1; i >= 0; i--) {
      if (contentHistory.value[i].field === editingField.value) return true
    }
    return false
  }

  function canRedoGeneration(): boolean {
    for (let i = historyIndex.value + 1; i < contentHistory.value.length; i++) {
      if (contentHistory.value[i].field === editingField.value) return true
    }
    return false
  }

  function findPrevSnapshotIdx(): number {
    for (let i = historyIndex.value - 1; i >= 0; i--) {
      if (contentHistory.value[i].field === editingField.value) return i
    }
    return -1
  }

  function findNextSnapshotIdx(): number {
    for (let i = historyIndex.value + 1; i < contentHistory.value.length; i++) {
      if (contentHistory.value[i].field === editingField.value) return i
    }
    return -1
  }

  function undoGeneration(): ContentSnapshot | null {
    const idx = findPrevSnapshotIdx()
    if (idx < 0) return null
    historyIndex.value = idx
    return contentHistory.value[idx]
  }

  function redoGeneration(): ContentSnapshot | null {
    const idx = findNextSnapshotIdx()
    if (idx < 0) return null
    historyIndex.value = idx
    return contentHistory.value[idx]
  }

  function toggleSidebar() {
    sidebarVisible.value = !sidebarVisible.value
  }

  function handleGenerateEvent(
    evt:
      | { type: 'generate_start'; target: string }
      | { type: 'generate_token'; target: string; token: string }
      | { type: 'generate_reset'; target: string }
      | { type: 'generate_done' }
      | { type: 'field_content'; target: string; content: string; highlights?: [number, number][] },
  ) {
    const target = 'target' in evt ? evt.target : ''
    const isChapter = target === 'chapter_new' || isChapterField(target)
    switch (evt.type) {
      case 'generate_start':
        isGenerating.value = true
        editingField.value = target
        mdPreviewMode.value = false
        if (target === 'chapter_new') { activeChapterIdx.value = null }
        else if (target.startsWith('chapter_')) { activeChapterIdx.value = parseInt(target.split('_')[1]) }
        if (isChapter) streamingChapterContent.value = ''
        else streamingFieldContent.value = ''
        delete fieldHighlights.value[target]
        delete preEditContent.value[target]
        break
      case 'generate_token':
        if (isChapter) streamingChapterContent.value += evt.token
        else streamingFieldContent.value += evt.token
        break
      case 'generate_reset':
        isGenerating.value = false
        if (isChapter) streamingChapterContent.value = ''
        else streamingFieldContent.value = ''
        delete fieldHighlights.value[target]
        delete preEditContent.value[target]
        break
      case 'generate_done':
        isGenerating.value = false
        fetchState()
        break
      case 'field_content':
        if (target && evt.content) {
          preEditContent.value[target] = fieldValues.value[target] || ''
          fieldValues.value[target] = evt.content
          if (evt.highlights && evt.highlights.length > 0) {
            fieldHighlights.value[target] = charHighlightsToLineNumbers(
              evt.content,
              evt.highlights as [number, number][]
            )
          } else {
            delete fieldHighlights.value[target]
          }
          editingField.value = target
          if (isChapter) streamingChapterContent.value = evt.content
          else streamingFieldContent.value = evt.content
        }
        break
    }
  }

  return {
    currentState,
    activeChapterIdx,
    editingField,
    sidebarVisible,
    mdPreviewMode,
    fieldValues,
    isDirty,
    hasUnsavedGenerated,
    contentHistory,
    historyIndex,
    isGenerating,
    abortController,
    pendingChapterTitle,
    fieldHighlights,
    preEditContent,
    streamingFieldContent,
    streamingChapterContent,
    chapters,
    currentBookName,
    hasOutline,
    isChapterField,
    isNewChapter,
    getChapterIdx,
    cleanPlaceholder,
    markDirty,
    resetDirty,
    pushContentSnapshot,
    canUndoGeneration,
    canRedoGeneration,
    undoGeneration,
    redoGeneration,
    fetchState,
    loadChapter,
    saveChapterEdit,
    saveNewChapter,
    removeChapter,
    saveFieldEdit,
    startGeneration,
    stopGeneration,
    toggleSidebar,
    handleGenerateEvent,
  }
})
