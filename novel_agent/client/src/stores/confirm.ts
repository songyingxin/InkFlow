import { defineStore } from 'pinia'
import { ref } from 'vue'

export type ConfirmVariant = 'default' | 'danger'

export interface ConfirmOptions {
  title?: string
  desc?: string
  confirmText?: string
  cancelText?: string
  variant?: ConfirmVariant
}

export const useConfirmStore = defineStore('confirm', () => {
  const visible = ref(false)
  const title = ref('')
  const desc = ref('')
  const confirmText = ref('确认')
  const cancelText = ref('取消')
  const variant = ref<ConfirmVariant>('default')

  let _resolver: ((val: boolean) => void) | null = null

  function confirm(options: ConfirmOptions | string): Promise<boolean> {
    const opts = typeof options === 'string' ? { desc: options } : options
    title.value = opts.title || '确认操作'
    desc.value = opts.desc || ''
    confirmText.value = opts.confirmText || '确认'
    cancelText.value = opts.cancelText || '取消'
    variant.value = opts.variant || 'default'
    return new Promise<boolean>((resolve) => {
      visible.value = true
      _resolver = resolve
    })
  }

  function resolve(value: boolean) {
    visible.value = false
    if (_resolver) { _resolver(value); _resolver = null }
  }

  function alert(options: ConfirmOptions | string): Promise<void> {
    const opts = typeof options === 'string' ? { desc: options } : options
    return confirm({
      title: opts.title || '提示',
      desc: opts.desc,
      confirmText: opts.confirmText || '知道了',
      cancelText: opts.cancelText || '',
      variant: opts.variant || 'default',
    }).then(() => undefined)
  }

  return { visible, title, desc, confirmText, cancelText, variant, confirm, alert, resolve }
})
