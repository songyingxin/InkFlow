<template>
  <div class="landing-root">
    <header class="landing-header">
      <div class="landing-logo"><span>墨</span>灵</div>
    </header>

    <div class="books-shell">
      <div class="books-inner">
        <div v-if="bookStore.loading" class="loading-state">
          <div class="loading-shimmer" />
          <span>加载书库中...</span>
        </div>

        <div v-else-if="bookStore.error" class="error-state">
          <div class="error-icon">!</div>
          <p class="error-title">连接失败</p>
          <p class="error-desc">{{ bookStore.error }}</p>
          <button class="error-retry" @click="bookStore.fetchBooks()">重试</button>
        </div>

        <div v-else-if="!bookStore.books.length" class="empty-state">
          <div class="empty-ornament">
            <svg width="28" height="28" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="0.7" stroke-linecap="round">
              <rect x="2" y="2" width="12" height="12" rx="2" /><line x1="5" y1="6" x2="11" y2="6" /><line x1="5" y1="9" x2="9" y2="9" />
            </svg>
          </div>
          <p class="empty-title">尚无作品</p>
          <p class="empty-desc">点击下方按钮开始第一部小说</p>
        </div>

        <div class="books-grid">
          <div
            v-for="(book, i) in bookStore.books"
            :key="book.name"
            class="book-card"
            :style="{ animationDelay: i * 60 + 'ms' }"
            @click="openBook(book.name)"
          >
            <div class="book-card-shimmer" />
            <div class="book-card-icon">
              <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M3 2v12l5-3 5 3V2a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1z" />
              </svg>
            </div>
            <div class="book-card-content">
              <div class="book-card-title">{{ book.title }}</div>
              <div class="book-card-meta">
                <span class="book-card-progress">{{ formatProgress(book.written_chapters, book.total_chapters) }}</span>
                <span class="book-card-sep">·</span>
                <span class="book-card-words">{{ formatWordCount(book.word_count) }}</span>
                <span v-if="book.updated_at" class="book-card-sep">·</span>
                <span v-if="book.updated_at" class="book-card-time">{{ formatTime(book.updated_at) }}</span>
              </div>
            </div>
            <button class="book-card-del" title="删除" aria-label="删除作品" @click.stop="showDeleteModal(book)">
              <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                <line x1="4" y1="4" x2="12" y2="12" /><line x1="12" y1="4" x2="4" y2="12" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="create-area">
      <button class="create-btn" @click="showCreateModal = true">
        <span class="create-btn-inner">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
            <line x1="8" y1="2" x2="8" y2="14" /><line x1="2" y1="8" x2="14" y2="8" />
          </svg>
        </span>
        <span>新建小说</span>
        <span class="create-btn-arrow">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2 6h8M7 3l3 3-3 3" />
          </svg>
        </span>
      </button>
    </div>

    <Teleport to="body">
      <div v-if="showCreateModal" class="modal-overlay" @click.self="showCreateModal = false" @keydown.esc="showCreateModal = false" tabindex="-1">
        <div class="modal">
          <div class="modal-eyebrow">新建</div>
          <h3>新建小说</h3>
          <p class="modal-desc">为你的作品命名，开始创作之旅</p>
          <input
            ref="createInputRef"
            v-model="createTitle"
            class="modal-input"
            type="text"
            placeholder="例如：凡人修仙传"
            @keydown.enter="confirmCreate"
            @keydown.esc="showCreateModal = false"
          />
          <div class="modal-actions">
            <button class="modal-btn modal-btn-cancel" @click="showCreateModal = false">取消</button>
            <button class="modal-btn modal-btn-confirm" :disabled="creating" @click="confirmCreate">
              <template v-if="creating">创建中...</template>
              <template v-else>
                创建
                <span class="modal-btn-arrow">
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M1 5h6M5 2l3 3-3 3" />
                  </svg>
                </span>
              </template>
            </button>
          </div>
        </div>
      </div>

      <div v-if="deleteTarget" class="modal-overlay" @click.self="deleteTarget = null" @keydown.esc="deleteTarget = null" tabindex="-1">
        <div class="modal">
          <div class="modal-eyebrow">危险操作</div>
          <h3>删除作品</h3>
          <p class="modal-desc">此操作将永久删除 <strong>{{ deleteTarget.title }}</strong>，包括所有章节和设定，不可恢复。</p>
          <div class="modal-actions">
            <button class="modal-btn modal-btn-cancel" @click="deleteTarget = null">取消</button>
            <button class="modal-btn modal-btn-danger" :disabled="deleting" @click="confirmDelete">
              {{ deleting ? '删除中...' : '确认删除' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useBookStore, useConfirmStore } from '@/stores'
import type { Book } from '@/types'

const router = useRouter()
const bookStore = useBookStore()
const confirmStore = useConfirmStore()

const showCreateModal = ref(false)
const createTitle = ref('')
const creating = ref(false)
const createInputRef = ref<HTMLInputElement>()

const deleteTarget = ref<Book | null>(null)
const deleting = ref(false)

function formatWordCount(n?: number): string {
  if (!n) return '0 字'
  if (n < 10000) return n + ' 字'
  return (n / 10000).toFixed(1) + ' 万字'
}

function formatProgress(written?: number, total?: number): string {
  const w = written ?? 0
  const t = total ?? 0
  if (t <= 0) return w > 0 ? w + ' 章已写' : '未开始'
  return w + ' / ' + t + ' 章'
}

function formatTime(ts?: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const day = 86400000
  if (diff < day && d.getDate() === now.getDate()) {
    return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0')
  }
  if (diff < day * 7) {
    const days = ['日', '一', '二', '三', '四', '五', '六']
    return '周' + days[d.getDay()]
  }
  return (d.getMonth() + 1) + '/' + d.getDate()
}

watch(showCreateModal, (val) => {
  if (val) {
    createTitle.value = ''
    nextTick(() => createInputRef.value?.focus())
  }
})

onMounted(() => {
  bookStore.fetchBooks()
})

async function openBook(name: string) {
  try {
    await bookStore.selectBook(name)
    router.push('/editor')
  } catch (e: any) {
    await confirmStore.alert({ title: '打开失败', desc: e.message })
  }
}

async function confirmCreate() {
  const title = createTitle.value.trim()
  if (!title) {
    createInputRef.value?.focus()
    return
  }
  creating.value = true
  try {
    await bookStore.createBook(title)
    router.push('/editor')
  } catch (e: any) {
    await confirmStore.alert({ title: '创建失败', desc: e.message })
  } finally {
    creating.value = false
  }
}

function showDeleteModal(book: Book) {
  deleteTarget.value = book
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  deleting.value = true
  try {
    await bookStore.deleteBook(deleteTarget.value.name)
    deleteTarget.value = null
  } catch (e: any) {
    await confirmStore.alert({ title: '删除失败', desc: e.message })
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.landing-root {
  max-width: 1000px;
  margin: 0 auto;
  padding: 80px 32px 120px;
  position: relative;
  z-index: 1;
}

.landing-header {
  text-align: center;
  margin-bottom: 56px;
  animation: reveal-up 700ms var(--spring-slow) both;
}

.landing-eyebrow {
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.22em;
  color: var(--accent);
  text-transform: uppercase;
  padding: 4px 10px;
  border: 1px solid rgba(var(--accent-rgb), 0.2);
  border-radius: 20px;
  margin-bottom: 20px;
}

.landing-logo {
  font-family: 'Noto Serif SC', serif;
  font-size: 48px;
  font-weight: 600;
  letter-spacing: -0.03em;
  color: var(--text-primary);
  line-height: 1.1;
}

.landing-logo span { color: var(--accent); font-weight: 700; }

.landing-subtitle {
  margin-top: 12px;
  font-size: 14px;
  color: var(--text-muted);
  font-weight: 400;
  letter-spacing: 0.02em;
}

.books-shell {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 6px;
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.02) inset,
    var(--shadow-card);
}

.books-inner {
  background: var(--bg-root);
  border: 1px solid var(--border-subtle);
  border-radius: calc(var(--radius-xl) - 6px);
  padding: 44px 40px;
  min-height: 200px;
}

.books-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 18px;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 60px 0;
  color: var(--text-faint);
  font-size: 13px;
  font-weight: 400;
}

.loading-shimmer {
  width: 200px;
  height: 4px;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--border) 25%, var(--border-subtle) 50%, var(--border) 75%);
  background-size: 200% 100%;
  animation: shimmer 2s infinite linear;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
}

.empty-ornament {
  width: 52px;
  height: 52px;
  border-radius: var(--radius-xl);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 18px;
  color: var(--text-faint);
}

.empty-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 18px;
  font-weight: 500;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.empty-desc {
  font-size: 13px;
  color: var(--text-faint);
}

.error-state {
  text-align: center;
  padding: 50px 20px;
}

.error-icon {
  width: 44px; height: 44px;
  border-radius: 50%;
  background: var(--rose-dim);
  border: 1px solid var(--rose);
  color: var(--rose);
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 16px;
  font-size: 18px; font-weight: 700;
}

.error-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 17px; font-weight: 600;
  color: var(--text-primary); margin-bottom: 6px;
}

.error-desc {
  font-size: 13px; color: var(--text-muted); margin-bottom: 20px; line-height: 1.6;
}

.error-retry {
  padding: 8px 20px;
  border: 1px solid var(--border); border-radius: 20px;
  background: var(--bg-raised); color: var(--text-secondary);
  font-size: 13px; font-weight: 500;
  transition: all var(--spring-fast);
}

.error-retry:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-dim); }

.book-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 22px 20px;
  cursor: pointer;
  transition: all var(--spring-medium);
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  overflow: hidden;
  animation: reveal-up 500ms var(--spring-slow) both;
}

.book-card-shimmer {
  position: absolute;
  inset: 0;
  opacity: 0;
  transition: opacity var(--spring-fast);
  background: radial-gradient(ellipse 100% 100% at 50% 0%, rgba(var(--accent-rgb), 0.04) 0%, transparent 60%);
  pointer-events: none;
}

.book-card:hover .book-card-shimmer { opacity: 1; }

.book-card:hover {
  border-color: rgba(var(--accent-rgb), 0.35);
  box-shadow:
    0 4px 24px rgba(0, 0, 0, 0.4),
    0 0 0 1px rgba(var(--accent-rgb), 0.1);
  transform: translateY(-2px);
  background: var(--bg-raised);
}

.book-card:active { transform: scale(0.985); transition: transform 100ms var(--spring-fast); }

.book-card-icon {
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(var(--accent-rgb), 0.12), rgba(var(--accent-rgb), 0.04));
  border-radius: var(--radius-md);
  color: var(--accent);
  flex-shrink: 0;
  border: 1px solid rgba(var(--accent-rgb), 0.12);
}

.book-card-content {
  flex: 1;
  min-width: 0;
}

.book-card-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.book-card-meta {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-faint);
  font-weight: 400;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.book-card-progress {
  color: var(--text-secondary);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.book-card-words {
  font-variant-numeric: tabular-nums;
}

.book-card-sep {
  color: var(--text-faint);
  opacity: 0.6;
}

.book-card-time {
  margin-left: auto;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10.5px;
}

.book-card-del {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-faint);
  opacity: 0;
  transition: all var(--spring-fast);
}

.book-card:hover .book-card-del { opacity: 0.6; }
.book-card-del:hover { opacity: 1; background: var(--rose-dim); color: var(--rose); }

.create-area {
  margin-top: 44px;
  display: flex;
  justify-content: center;
  animation: fade-up 600ms var(--spring-slow) both;
  animation-delay: 200ms;
}

.create-btn {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 12px 24px 12px 14px;
  border: 2px dashed var(--border);
  border-radius: 40px;
  background: transparent;
  color: var(--text-muted);
  font-size: 14px;
  font-weight: 500;
  transition: all var(--spring-medium);
}

.create-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-dim);
  gap: 14px;
}

.create-btn-inner {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(var(--accent-rgb), 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  transition: all var(--spring-medium);
}

.create-btn:hover .create-btn-inner {
  background: rgba(var(--accent-rgb), 0.18);
  transform: scale(1.1);
}

.create-btn-arrow {
  display: flex;
  align-items: center;
  opacity: 0;
  transform: translateX(-6px);
  transition: all var(--spring-medium);
}

.create-btn:hover .create-btn-arrow {
  opacity: 1;
  transform: translateX(0);
}

.modal-overlay {
  position: fixed;
  inset: 0;
  background: var(--overlay-bg);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  animation: fade-in 180ms var(--spring-fast) both;
}

.modal {
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 28px 32px 22px;
  width: 440px;
  max-width: 92vw;
  box-shadow:
    0 24px 64px rgba(0, 0, 0, 0.7),
    0 0 0 1px var(--border-subtle);
  animation: modal-in 350ms var(--spring-slow) both;
}

.modal-eyebrow {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.18em;
  color: var(--accent);
  text-transform: uppercase;
  margin-bottom: 10px;
}

.modal h3 {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 6px;
  letter-spacing: -0.02em;
}

.modal .modal-desc {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 20px;
  line-height: 1.6;
}

.modal .modal-desc strong {
  color: var(--text-primary);
  font-weight: 600;
}

.modal .modal-input {
  width: 100%;
  padding: 13px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 14px;
  outline: none;
  font-family: 'Noto Serif SC', serif;
  transition: all var(--spring-fast);
  margin-bottom: 22px;
  caret-color: var(--accent);
}

.modal .modal-input:focus {
  border-color: rgba(var(--accent-rgb), 0.5);
  box-shadow: 0 0 0 3px var(--accent-dim);
}

.modal .modal-input::placeholder { color: var(--text-faint); }

.modal .modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}

.modal .modal-btn {
  padding: 10px 22px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 500;
  transition: all var(--spring-fast);
}

.modal .modal-btn-cancel {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-muted);
}

.modal .modal-btn-cancel:hover {
  background: var(--bg-hover);
  color: var(--text-secondary);
  border-color: var(--border-strong);
}

.modal .modal-btn-confirm {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: var(--accent);
  color: var(--accent-on);
  font-weight: 600;
  border-radius: 24px;
  padding: 10px 22px;
}

.modal .modal-btn-confirm:hover { background: var(--accent-strong); transform: scale(1.02); }
.modal .modal-btn-confirm:active { transform: scale(0.97); }
.modal .modal-btn-confirm:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }

.modal-btn-arrow {
  display: inline-flex;
  align-items: center;
  transition: transform var(--spring-fast);
}

.modal .modal-btn-confirm:hover .modal-btn-arrow {
  transform: translateX(2px);
}

.modal .modal-btn-danger {
  border: none;
  background: var(--rose);
  color: #fff;
  font-weight: 600;
  border-radius: var(--radius-sm);
  padding: 10px 22px;
}

.modal .modal-btn-danger:hover { background: var(--rose-strong); }
.modal .modal-btn-danger:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
