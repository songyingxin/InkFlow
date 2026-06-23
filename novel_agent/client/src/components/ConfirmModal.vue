<template>
  <Teleport to="body">
    <div v-if="confirmStore.visible" class="modal-overlay" @click.self="onCancel">
      <div class="modal" @keydown.esc="onCancel" tabindex="0" ref="modalRef">
        <div class="modal-eyebrow" :class="{ danger: isDanger }">
          {{ isDanger ? '危险操作' : '提示' }}
        </div>
        <h3>{{ confirmStore.title }}</h3>
        <p v-if="confirmStore.desc" class="modal-desc" v-text="confirmStore.desc" />
        <div class="modal-actions">
          <button v-if="confirmStore.cancelText" class="modal-btn modal-btn-cancel" @click="onCancel">
            {{ confirmStore.cancelText }}
          </button>
          <button
            class="modal-btn"
            :class="isDanger ? 'modal-btn-danger' : 'modal-btn-confirm'"
            @click="onConfirm"
          >
            {{ confirmStore.confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { useConfirmStore } from '@/stores'

const confirmStore = useConfirmStore()
const modalRef = ref<HTMLDivElement>()

const isDanger = computed(() => confirmStore.variant === 'danger')

watch(() => confirmStore.visible, (v) => {
  if (v) {
    nextTick(() => modalRef.value?.focus())
    window.addEventListener('keydown', onKeydown)
  } else {
    window.removeEventListener('keydown', onKeydown)
  }
})

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    onCancel()
  } else if (e.key === 'Enter') {
    e.preventDefault()
    onConfirm()
  }
}

function onConfirm() { confirmStore.resolve(true) }
function onCancel() { confirmStore.resolve(false) }
</script>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: var(--overlay-bg); backdrop-filter: blur(6px);
  z-index: 200; display: flex; align-items: center; justify-content: center;
  animation: fade-in 180ms var(--spring-fast) both;
}

.modal {
  background: var(--bg-raised); border: 1px solid var(--border);
  border-radius: var(--radius-lg); padding: 28px 32px 22px;
  width: 440px; max-width: 92vw; outline: none;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.7), 0 0 0 1px var(--border-subtle);
  animation: modal-in 350ms var(--spring-slow) both;
}

.modal-eyebrow {
  font-family: 'JetBrains Mono', monospace; font-size: 9.5px; font-weight: 500;
  letter-spacing: 0.18em; color: var(--accent); text-transform: uppercase; margin-bottom: 10px;
}
.modal-eyebrow.danger { color: var(--rose); }

.modal h3 {
  font-family: 'Noto Serif SC', serif; font-size: 22px; font-weight: 600;
  color: var(--text-primary); margin-bottom: 6px; letter-spacing: -0.02em;
}

.modal-desc {
  font-size: 13px; color: var(--text-muted); margin-bottom: 22px; line-height: 1.6;
  white-space: pre-wrap; word-break: break-word;
}

.modal-actions { display: flex; gap: 10px; justify-content: flex-end; }

.modal-btn {
  padding: 10px 22px; border-radius: var(--radius-sm);
  font-size: 13px; font-weight: 500; transition: all var(--spring-fast);
}

.modal-btn-cancel {
  border: 1px solid var(--border); background: transparent; color: var(--text-muted);
}
.modal-btn-cancel:hover { background: var(--bg-hover); color: var(--text-secondary); border-color: var(--border-strong); }

.modal-btn-confirm {
  border: none; background: var(--accent); color: var(--accent-on);
  font-weight: 600; border-radius: 24px;
}
.modal-btn-confirm:hover { background: var(--accent-strong); transform: scale(1.02); }
.modal-btn-confirm:active { transform: scale(0.97); }

.modal-btn-danger {
  border: none; background: var(--rose); color: #fff;
  font-weight: 600; border-radius: var(--radius-sm);
}
.modal-btn-danger:hover { background: var(--rose-strong); }
</style>
