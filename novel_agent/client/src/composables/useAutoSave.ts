import { watch, nextTick, type WatchStopHandle } from 'vue'
import { useEditorStore } from '@/stores'

const DEBOUNCE_MS = 5000
const MAX_DIRTY_MS = 30000

export function useAutoSave(doSaveCurrent: (isAuto?: boolean) => Promise<void>) {
  const editorStore = useEditorStore()
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let maxDirtyTimer: ReturnType<typeof setTimeout> | null = null
  let dirtyWatcher: WatchStopHandle | null = null
  let scheduledSave: Promise<void> | null = null

  function stopGeneratedSaveTimer() {
    scheduledSave = null
  }

  function startGeneratedSaveTimer() {
    stopGeneratedSaveTimer()
    editorStore.hasUnsavedGenerated = true
    scheduledSave = nextTick().then(() => {
      if (!scheduledSave) return
      editorStore.hasUnsavedGenerated = false
      scheduledSave = null
      return doSaveCurrent(true)
    })
  }

  function _scheduleSave() {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      if (!editorStore.isDirty || editorStore.isGenerating) return
      _clearMaxDirty()
      doSaveCurrent(true)
    }, DEBOUNCE_MS)
  }

  function _clearMaxDirty() {
    if (maxDirtyTimer) { clearTimeout(maxDirtyTimer); maxDirtyTimer = null }
  }

  function startAutoSave() {
    stopAutoSave()
    editorStore.resetDirty()

    dirtyWatcher = watch(
      () => editorStore.isDirty,
      (dirty) => {
        if (!dirty || editorStore.isGenerating) return
        _scheduleSave()
        if (!maxDirtyTimer) {
          maxDirtyTimer = setTimeout(() => {
            if (!editorStore.isDirty || editorStore.isGenerating) { maxDirtyTimer = null; return }
            maxDirtyTimer = null
            doSaveCurrent(true)
          }, MAX_DIRTY_MS)
        }
      },
    )
  }

  function stopAutoSave() {
    if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null }
    _clearMaxDirty()
    if (dirtyWatcher) { dirtyWatcher(); dirtyWatcher = null }
    editorStore.resetDirty()
  }

  return {
    startGeneratedSaveTimer,
    stopGeneratedSaveTimer,
    startAutoSave,
    stopAutoSave,
  }
}
