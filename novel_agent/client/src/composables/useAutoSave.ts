import { useEditorStore } from '@/stores'

const AUTO_SAVE_INTERVAL = 60000

export function useAutoSave(doSaveCurrent: (isAuto?: boolean) => Promise<void>) {
  const editorStore = useEditorStore()
  let autoSaveTimer: ReturnType<typeof setInterval> | null = null
  let generatedSaveTimer: ReturnType<typeof setTimeout> | null = null

  function stopGeneratedSaveTimer() {
    if (generatedSaveTimer) { clearTimeout(generatedSaveTimer); generatedSaveTimer = null }
  }

  function startGeneratedSaveTimer() {
    stopGeneratedSaveTimer()
    editorStore.hasUnsavedGenerated = true
    generatedSaveTimer = setTimeout(() => {
      editorStore.hasUnsavedGenerated = false
      generatedSaveTimer = null
      doSaveCurrent(true)
    }, 0)
  }

  function startAutoSave() {
    stopAutoSave()
    editorStore.resetDirty()
    autoSaveTimer = setInterval(() => {
      if (!editorStore.isDirty || editorStore.isGenerating) return
      doSaveCurrent(true)
    }, AUTO_SAVE_INTERVAL)
  }

  function stopAutoSave() {
    if (autoSaveTimer) { clearInterval(autoSaveTimer); autoSaveTimer = null }
    editorStore.resetDirty()
  }

  return {
    startGeneratedSaveTimer,
    stopGeneratedSaveTimer,
    startAutoSave,
    stopAutoSave,
  }
}
