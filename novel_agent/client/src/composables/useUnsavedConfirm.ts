import { ref } from 'vue'
import { useEditorStore } from '@/stores'
import { FIELD_LABELS, FIELD_TITLES } from '@/types'

export function useUnsavedConfirm() {
  const editorStore = useEditorStore()

  const showUnsavedModal = ref(false)
  const unsavedModalTitle = ref('未保存的修改')
  const unsavedModalDesc = ref('')
  let _resolver: ((val: 'cancel' | 'discard' | 'save') => void) | null = null

  function getFieldDisplayName() {
    const f = editorStore.editingField
    if (f === 'chapter_new') return '新建章节'
    if (editorStore.isChapterField(f)) return '第' + editorStore.getChapterIdx() + '章'
    return FIELD_LABELS[f] || FIELD_TITLES[f] || f
  }

  function confirmUnsavedBeforeAction(actionLabel: string): Promise<'cancel' | 'discard' | 'save'> {
    if (!editorStore.isDirty && !editorStore.hasUnsavedGenerated) return Promise.resolve('discard')
    const name = getFieldDisplayName()
    unsavedModalTitle.value = '未保存的内容'
    unsavedModalDesc.value = '「' + name + '」有未保存的修改，是否' + actionLabel + '前保存？'
    return new Promise<'cancel' | 'discard' | 'save'>((resolve) => {
      showUnsavedModal.value = true
      _resolver = resolve
    })
  }

  function resolveUnsavedAction(action: 'cancel' | 'discard' | 'save') {
    showUnsavedModal.value = false
    if (_resolver) { _resolver(action); _resolver = null }
  }

  return {
    showUnsavedModal,
    unsavedModalTitle,
    unsavedModalDesc,
    confirmUnsavedBeforeAction,
    resolveUnsavedAction,
  }
}
