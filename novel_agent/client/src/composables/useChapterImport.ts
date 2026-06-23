import { ref } from 'vue'
import { useEditorStore, useChatStore } from '@/stores'
import * as api from '@/api'

export function useChapterImport() {
  const editorStore = useEditorStore()
  const chatStore = useChatStore()

  const showImportModal = ref(false)
  const importFile = ref<File | null>(null)
  const importing = ref(false)
  const importProgress = ref(0)
  const importProgressText = ref('')
  const importPreview = ref<string[]>([])
  const importDragActive = ref(false)
  const fileInputRef = ref<HTMLInputElement>()

  function onDragOver() { importDragActive.value = true }
  function onDragLeave() { importDragActive.value = false }
  function onDrop(e: DragEvent) {
    importDragActive.value = false
    if (e.dataTransfer?.files.length) setImportFile(e.dataTransfer.files[0])
  }
  function onFileChange(e: Event) {
    const t = e.target as HTMLInputElement
    if (t.files?.length) setImportFile(t.files[0])
  }

  function setImportFile(file: File) {
    importFile.value = file
    importPreview.value = []
    const reader = new FileReader()
    reader.onload = (ev) => {
      try {
        const text = ev.target?.result as string
        const data = JSON.parse(text)
        const arr = Array.isArray(data) ? data : (typeof data === 'object' ? [data] : [])
        importPreview.value = arr.map((ch: any) => ch.title || ch['标题'] || '未命名')
      } catch { importPreview.value = [] }
    }
    reader.readAsText(file)
  }

  async function confirmImport() {
    if (!importFile.value) return
    importing.value = true
    importProgress.value = 30
    importProgressText.value = '正在上传并解析...'
    try {
      const data = await api.importChaptersBatch(importFile.value)
      importProgress.value = 100
      importProgressText.value = '导入完成！共 ' + data.imported_count + ' 章'
      await editorStore.fetchState()
      chatStore.addAgentMessage('导入完成，共 ' + data.imported_count + ' 章')
      setTimeout(() => {
        showImportModal.value = false
        importFile.value = null
        importPreview.value = []
      }, 600)
    } catch (e: any) {
      importProgressText.value = '导入失败'
      chatStore.addAgentMessage('导入失败：' + e.message)
    } finally {
      importing.value = false
    }
  }

  return {
    showImportModal,
    importFile,
    importing,
    importProgress,
    importProgressText,
    importPreview,
    importDragActive,
    fileInputRef,
    onDragOver,
    onDragLeave,
    onDrop,
    onFileChange,
    setImportFile,
    confirmImport,
  }
}
