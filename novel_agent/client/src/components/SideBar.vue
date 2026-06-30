<template>
  <div class="sidebar" :class="{ collapsed: !editorStore.sidebarVisible }">
    <div class="sidebar-body">
      <template v-if="editorStore.currentState">
        <div class="sb-book-row" :class="{ active: editorStore.editingField === 'title' }" @click="openFieldEditor('title')">
          <span class="sb-book-icon"><SbIcon name="book" /></span>
          <span class="sb-book-name">{{ bookTitle }}</span>
        </div>

        <div class="sb-quick-section">
          <div class="sb-quick-label">创作依据</div>
          <div class="sb-quick-grid">
            <button
              v-for="sf in SIDEBAR_FIELDS"
              :key="sf.field"
              class="sb-quick-btn"
              :class="{ active: editorStore.editingField === sf.field }"
              @click="openFieldEditor(sf.field)"
              :title="sf.label"
            >
              <SbIcon :name="sf.icon" />
              <span>{{ sf.label }}</span>
              <svg
                v-if="sf.genFn"
                class="sb-quick-gen"
                :disabled="editorStore.isGenerating"
                @click.stop="handleGenClick(sf.genFn)"
                width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"
              >
                <path d="M8 2l1.5 5.5L15 8l-5.5 1.5L8 14 6.5 8.5 1 8l5.5-1.5z"/>
              </svg>
            </button>
          </div>
        </div>

        <div class="sb-ch-section">
          <div class="sb-ch-header">
            <span class="sb-ch-title">章节</span>
            <div class="sb-ch-actions">
              <button class="sb-ch-add-btn" @click="addChapter" title="新建章节">
                <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                  <line x1="8" y1="2" x2="8" y2="14" /><line x1="2" y1="8" x2="14" y2="8" />
                </svg>
              </button>
            </div>
          </div>

          <div class="sb-ch-search-wrap">
            <svg class="sb-ch-search-icon" width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
              <circle cx="7" cy="7" r="5" /><line x1="11" y1="11" x2="14" y2="14" />
            </svg>
            <input
              v-model="chapterQuery"
              class="sb-ch-search"
              placeholder="搜索章节..."
            />
          </div>

          <ul v-if="filteredChapters.length" class="sb-ch-list">
            <li
              v-for="(ch, i) in filteredChapters"
              :key="ch.idx"
              class="sb-ch-item"
              :class="{ active: editorStore.activeChapterIdx === ch.idx }"
              @click="loadChapter(ch.idx)"
            >
              <span class="sb-ch-dot" :class="getChapterDotClass(ch, i)" />
              <span class="sb-ch-idx">{{ ch.idx }}</span>
              <span class="sb-ch-name">{{ ch.title || '（空）' }}</span>
              <button class="sb-ch-hist" title="版本历史" aria-label="版本历史" @click.stop="openVersionHistory(ch.idx)">
                <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="8" cy="8" r="6.5" /><polyline points="8,5 8,8 11,9" />
                </svg>
              </button>
              <button class="sb-ch-del" title="删除" aria-label="删除章节" @click.stop="deleteChapter(ch.idx)">
                <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
                  <line x1="4" y1="4" x2="12" y2="12" /><line x1="12" y1="4" x2="4" y2="12" />
                </svg>
              </button>
            </li>
          </ul>
          <div v-else class="sb-ch-empty">
            {{ chapterQuery ? '无匹配章节' : '暂无章节' }}
          </div>

          <ul v-if="deletedChapters.length && !chapterQuery" class="sb-ch-list sb-ch-list-deleted">
            <li class="sb-ch-section-label">已删除</li>
            <li
              v-for="idx in deletedChapters"
              :key="'del-' + idx"
              class="sb-ch-item sb-ch-item-deleted"
            >
              <span class="sb-ch-dot deleted" />
              <span class="sb-ch-idx">{{ idx }}</span>
              <span class="sb-ch-name">第 {{ idx }} 章</span>
              <button class="sb-ch-hist" title="版本历史" aria-label="版本历史" @click.stop="openVersionHistory(idx)">
                <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="8" cy="8" r="6.5" /><polyline points="8,5 8,8 11,9" />
                </svg>
              </button>
            </li>
          </ul>
        </div>
      </template>

      <div v-else class="sb-empty-state">
        <div class="sb-empty-ornament">
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="0.9" stroke-linecap="round">
            <rect x="2" y="2" width="12" height="12" rx="2" /><line x1="5" y1="6" x2="11" y2="6" /><line x1="5" y1="9" x2="9" y2="9" />
          </svg>
        </div>
        <p>尚未加载作品。<br>请返回书库选择。</p>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="showHistModal" class="modal-overlay" @click.self="showHistModal = false" @keydown.esc="showHistModal = false" tabindex="-1">
        <div class="modal modal-wide">
          <div class="modal-eyebrow">版本历史</div>
          <h3>第 {{ histChapterIdx }} 章 <span v-if="!histChapterExists" class="hist-deleted-badge">已删除</span></h3>
          <div v-if="histLoading" class="hist-loading">加载中...</div>
          <template v-else-if="histBackups.length">
            <div class="hist-current" v-if="histChapterExists">
              当前版本（{{ histCurrentSize }}字）
              <span v-if="histCurrentHash" class="hist-hash">{{ histCurrentHash.slice(0, 8) }}</span>
            </div>
            <ul class="hist-list">
              <li
                v-for="bp in histBackups"
                :key="bp.timestamp"
                class="hist-item"
              >
                <div class="hist-item-meta">
                  <span class="hist-date">{{ bp.date }}</span>
                  <span class="hist-time">{{ bp.time }}</span>
                  <span class="hist-size">{{ bp.size }}字</span>
                  <span v-if="bp.hash === histCurrentHash" class="hist-tag-same">与当前相同</span>
                </div>
                <p class="hist-preview">{{ bp.preview }}</p>
                <div class="hist-item-actions">
                  <button
                    class="btn btn-ghost btn-sm"
                    :disabled="histPreviewing === bp.timestamp"
                    @click="previewHistBackup(bp.timestamp)"
                  >
                    {{ histPreviewing === bp.timestamp ? '加载中...' : '预览' }}
                  </button>
                  <button
                    class="btn btn-ghost btn-sm"
                    :disabled="histRestoring === bp.timestamp || bp.hash === histCurrentHash"
                    @click="restoreHistBackup(bp.timestamp)"
                  >
                    {{ histRestoring === bp.timestamp ? '恢复中...' : '恢复' }}
                  </button>
                </div>
              </li>
            </ul>
          </template>
          <p v-else class="hist-empty">暂无历史版本</p>
          <div v-if="histPreviewContent" class="hist-preview-panel">
            <div class="hist-preview-header">
              <span>备份预览（{{ histPreviewDate }}）</span>
              <button class="btn btn-ghost btn-sm" @click="histPreviewContent = ''">关闭</button>
            </div>
            <pre class="hist-preview-body">{{ histPreviewContent }}</pre>
          </div>
          <div class="modal-actions">
            <button class="modal-btn modal-btn-cancel" @click="showHistModal = false">关闭</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useEditorStore, useConfirmStore, useChatStore } from '@/stores'
import { SIDEBAR_FIELDS } from '@/types'
import type { Chapter } from '@/types'
import SbIcon from './SbIcon.vue'

const emit = defineEmits<{
  fieldChanged: []
  genField: [field: string]
}>()

const editorStore = useEditorStore()
const confirmStore = useConfirmStore()
const chatStore = useChatStore()

const chapterQuery = ref('')

const bookTitle = computed(() => {
  const s = editorStore.currentState
  return s?.meta?.title || s?.outline?.title || '未命名'
})

const visibleChapters = computed(() => {
  return editorStore.chapters.filter(ch => ch.is_written || ch.title || ch.content_summary)
})

const deletedChapters = computed(() => {
  return editorStore.currentState?.deleted_chapters || []
})

const filteredChapters = computed(() => {
  const q = chapterQuery.value.trim().toLowerCase()
  if (!q) return visibleChapters.value
  return visibleChapters.value.filter(ch => {
    const title = (ch.title || '').toLowerCase()
    const idx = String(ch.idx)
    return title.includes(q) || idx.includes(q)
  })
})

function getChapterDotClass(ch: Chapter, index: number) {
  if (ch.is_written) return 'done'
  const firstUnwritten = visibleChapters.value.findIndex(c => !c.is_written)
  if (index === firstUnwritten) return 'now'
  return 'wait'
}

async function openFieldEditor(field: string) {
  if (editorStore.isGenerating) {
    editorStore.pinView(field)
  } else {
    editorStore.editingField = field
  }
  editorStore.mdPreviewMode = false
  emit('fieldChanged')
}

async function loadChapter(idx: number) {
  try {
    await editorStore.loadChapter(idx)
    if (editorStore.isGenerating) {
      editorStore.pinView('chapter_' + idx)
    }
    emit('fieldChanged')
  } catch (e: any) { console.error('Load chapter failed:', e) }
}

function addChapter() {
  if (editorStore.isGenerating) {
    editorStore.pinView('chapter_new')
  } else {
    editorStore.editingField = 'chapter_new'
    editorStore.activeChapterIdx = null
  }
  editorStore.mdPreviewMode = false
  emit('fieldChanged')
}

async function deleteChapter(idx: number) {
  const ok = await confirmStore.confirm({
    title: '删除章节',
    desc: '确定删除第 ' + idx + ' 章？10 天内可从版本历史恢复。',
    confirmText: '确认删除',
    variant: 'danger',
  })
  if (!ok) return
  try {
    await editorStore.removeChapter(idx)
    emit('fieldChanged')
    await chatStore.loadHistory()
  } catch (e: any) { console.error('Delete chapter failed:', e) }
}

const showHistModal = ref(false)
const histChapterIdx = ref(0)
const histLoading = ref(false)
const histBackups = ref<{ timestamp: string; date: string; time: string; size: number; preview: string; hash: string }[]>([])
const histCurrentHash = ref('')
const histCurrentSize = ref(0)
const histRestoring = ref('')
const histPreviewing = ref('')
const histPreviewContent = ref('')
const histPreviewDate = ref('')
const histChapterExists = ref(true)

async function openVersionHistory(idx: number) {
  showHistModal.value = true
  histChapterIdx.value = idx
  histLoading.value = true
  histBackups.value = []
  histCurrentHash.value = ''
  histCurrentSize.value = 0
  histPreviewContent.value = ''
  histChapterExists.value = true
  try {
    const data = await import('@/api').then(m => m.listBackups(idx))
    histBackups.value = data.backups
    histCurrentHash.value = data.current_hash
    const ch = editorStore.currentState?.chapters?.find(c => c.idx === idx)
    if (ch) {
      histCurrentSize.value = ch.content?.length || 0
    } else {
      histChapterExists.value = false
    }
  } catch (e: any) { console.error('List backups failed:', e) }
  finally { histLoading.value = false }
}

async function previewHistBackup(timestamp: string) {
  histPreviewing.value = timestamp
  histPreviewContent.value = ''
  try {
    const data = await import('@/api').then(m => m.previewBackup(histChapterIdx.value, timestamp))
    histPreviewContent.value = data.content
    histPreviewDate.value = data.timestamp.slice(0, 16)
  } catch (e: any) { console.error('Preview backup failed:', e) }
  finally { histPreviewing.value = '' }
}

async function restoreHistBackup(timestamp: string) {
  const ok = await confirmStore.confirm({
    title: '恢复历史版本',
    desc: `确定将第 ${histChapterIdx.value} 章恢复到 ${timestamp.slice(0, 16)} 的版本？当前版本会自动备份。`,
    confirmText: '确认恢复',
    variant: 'danger',
  })
  if (!ok) return
  histRestoring.value = timestamp
  try {
    const data = await import('@/api').then(m => m.restoreBackup(histChapterIdx.value, timestamp))
    editorStore.applyRemoteState(data.state)
    emit('fieldChanged')
    await chatStore.loadHistory()
    histPreviewContent.value = ''
    await openVersionHistory(histChapterIdx.value)
  } catch (e: any) { console.error('Restore backup failed:', e) }
  finally { histRestoring.value = '' }
}

function handleGenClick(genFn: string) {
  if (genFn === 'generateOutline') {
    emit('genField', 'outline_future_md_content')
  }
}
</script>

<style scoped>
.sidebar {
  background: var(--bg-surface);
  border-right: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: width var(--spring-slow);
  position: relative;
}

.sidebar.collapsed { width: 0; overflow: hidden; }

.sidebar-body {
  flex: 1;
  overflow-y: auto;
  width: var(--sidebar-w);
  display: flex;
  flex-direction: column;
}

.sidebar-body::-webkit-scrollbar { width: 3px; }
.sidebar-body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
.sidebar-body::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }

.sb-book-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
  border-bottom: 1px solid var(--border-subtle);
  border-left: 2px solid transparent;
  transition: all var(--spring-fast);
}

.sb-book-row:hover { background: var(--bg-hover); }
.sb-book-row.active { background: var(--accent-dim); border-left-color: var(--accent); }

.sb-book-icon {
  flex-shrink: 0; width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
  color: var(--accent);
}

.sb-book-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: 'Noto Serif SC', serif;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sb-quick-section {
  padding: 12px 12px 14px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border-subtle);
}

.sb-quick-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.14em;
  color: var(--text-faint);
  text-transform: uppercase;
  padding: 0 4px 8px;
}

.sb-quick-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 5px;
}

.sb-quick-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--bg-raised);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
  transition: all var(--spring-fast);
  position: relative;
}

.sb-quick-btn:hover { background: var(--bg-hover); border-color: var(--accent); color: var(--accent); }
.sb-quick-btn.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }

.sb-quick-btn svg { flex-shrink: 0; opacity: 0.7; }
.sb-quick-btn.active svg { opacity: 1; }

.sb-quick-btn span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: 'Noto Serif SC', serif;
}

.sb-quick-gen {
  position: absolute;
  top: 3px; right: 3px;
  opacity: 0;
  color: var(--text-faint);
  transition: opacity var(--spring-fast);
}

.sb-quick-btn:hover .sb-quick-gen { opacity: 0.6; }
.sb-quick-gen:hover { opacity: 1; color: var(--accent); }

.sb-ch-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 10px 12px 12px;
}

.sb-ch-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 8px;
}

.sb-ch-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.14em;
  color: var(--text-faint);
  text-transform: uppercase;
}

.sb-ch-actions {
  display: flex;
  gap: 4px;
}

.sb-ch-search-wrap {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  flex-shrink: 0;
}

.sb-ch-search-icon {
  position: absolute;
  left: 8px;
  color: var(--text-faint);
  pointer-events: none;
}

.sb-ch-search {
  width: 100%;
  padding: 6px 8px 6px 26px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 11.5px;
  outline: none;
  transition: all var(--spring-fast);
}

.sb-ch-search:focus { border-color: var(--accent); background: var(--bg-raised); }
.sb-ch-search::placeholder { color: var(--text-faint); }

.sb-ch-add-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 24px; height: 24px;
  border: none; border-radius: var(--radius-sm);
  background: var(--accent); color: var(--accent-on);
  transition: all var(--spring-fast);
}

.sb-ch-add-btn:hover { background: var(--accent-strong); }
.sb-ch-add-btn:active { transform: scale(0.96); }

.sb-ch-list {
  list-style: none;
  padding: 0;
  margin: 0;
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.sb-ch-list::-webkit-scrollbar { width: 3px; }
.sb-ch-list::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

.sb-ch-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 8px; border-radius: var(--radius-sm);
  cursor: pointer; font-size: 12px;
  transition: all var(--spring-fast);
  border: 1px solid transparent;
}

.sb-ch-item:hover { background: var(--bg-hover); }
.sb-ch-item.active { background: var(--accent-dim); border-color: rgba(var(--accent-rgb), 0.15); }

.sb-ch-dot {
  width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0;
}

.sb-ch-dot.done { background: var(--sage); }
.sb-ch-dot.wait { background: var(--border-strong); }
.sb-ch-dot.now { background: var(--amber); box-shadow: 0 0 5px rgba(200, 136, 58, 0.4); }

.sb-ch-idx {
  font-size: 10px; color: var(--text-faint);
  font-family: 'JetBrains Mono', monospace; min-width: 18px;
}

.sb-ch-name {
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--text-secondary);
  font-family: 'Noto Serif SC', serif;
}

.sb-ch-item.active .sb-ch-name { color: var(--text-primary); }

.sb-ch-del {
  width: 18px; height: 18px;
  border: none; background: none;
  color: var(--text-faint);
  display: flex; align-items: center; justify-content: center;
  border-radius: 4px; opacity: 0;
  transition: all var(--spring-fast);
}

.sb-ch-item:hover .sb-ch-del { opacity: 0.5; }
.sb-ch-del:hover { opacity: 1; background: var(--rose-dim); color: var(--rose); }

.sb-ch-hist {
  width: 18px; height: 18px;
  border: none; background: none;
  color: var(--text-faint);
  display: flex; align-items: center; justify-content: center;
  border-radius: 4px; opacity: 0;
  transition: all var(--spring-fast);
}

.sb-ch-item:hover .sb-ch-hist { opacity: 0.5; }
.sb-ch-hist:hover { opacity: 1; background: var(--accent-dim); color: var(--accent); }

.sb-ch-list-deleted {
  border-top: 1px solid var(--border-subtle);
  padding-top: 6px;
  margin-top: 4px;
}

.sb-ch-section-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.14em;
  color: var(--rose);
  text-transform: uppercase;
  padding: 4px 8px 2px;
}

.sb-ch-item-deleted {
  opacity: 0.55;
  cursor: default;
}

.sb-ch-item-deleted:hover { opacity: 0.8; background: var(--bg-hover); }

.sb-ch-dot.deleted { background: var(--rose); }

.sb-ch-item-deleted .sb-ch-hist { opacity: 0 !important; }
.sb-ch-item-deleted:hover .sb-ch-hist { opacity: 0.6 !important; }
.sb-ch-item-deleted .sb-ch-hist:hover { opacity: 1 !important; }

.sb-ch-empty {
  font-size: 12px; color: var(--text-faint);
  font-family: 'Noto Serif SC', serif;
  padding: 12px 8px;
  text-align: center;
}

.sb-empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 48px 20px; text-align: center; color: var(--text-faint);
}

.sb-empty-ornament {
  width: 44px; height: 44px;
  border-radius: var(--radius-md);
  background: var(--bg-raised); border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 14px; color: var(--border-strong);
}

.sb-empty-state p { font-size: 12px; line-height: 1.8; font-family: 'Noto Serif SC', serif; }

.hist-loading {
  font-size: 13px; color: var(--text-faint); padding: 20px 0; text-align: center;
}

.hist-current {
  font-size: 12px; color: var(--text-secondary);
  padding: 8px 0 12px;
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 8px;
}

.hist-hash {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px; color: var(--text-faint); margin-left: 8px;
}

.hist-deleted-badge {
  font-size: 11px; color: var(--rose); background: var(--rose-dim);
  padding: 1px 6px; border-radius: 3px; margin-left: 6px; font-weight: 400;
}

.hist-list {
  list-style: none; padding: 0; margin: 0; max-height: 320px; overflow-y: auto;
}

.hist-item {
  padding: 10px 0;
  border-bottom: 1px solid var(--border-subtle);
}

.hist-item-meta {
  display: flex; align-items: center; gap: 10px; margin-bottom: 4px;
  font-size: 11px;
}

.hist-date { color: var(--text-primary); font-weight: 500; }
.hist-time { color: var(--text-faint); font-family: 'JetBrains Mono', monospace; }
.hist-size { color: var(--text-faint); }

.hist-tag-same {
  font-size: 10px; color: var(--sage); background: var(--sage-dim);
  padding: 1px 6px; border-radius: 3px;
}

.hist-preview {
  font-size: 11px; color: var(--text-faint);
  font-family: 'Noto Serif SC', serif;
  margin: 0 0 6px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.hist-item-actions {
  display: flex; gap: 6px;
}

.hist-empty {
  font-size: 13px; color: var(--text-faint); padding: 20px 0; text-align: center;
}

.hist-preview-panel {
  margin-top: 12px; border-top: 1px solid var(--border-subtle); padding-top: 10px;
}

.hist-preview-header {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11px; color: var(--text-secondary); margin-bottom: 8px;
}

.hist-preview-body {
  font-size: 12px; font-family: 'Noto Serif SC', serif;
  color: var(--text-primary);
  background: var(--bg-raised);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  padding: 12px;
  max-height: 240px; overflow-y: auto;
  white-space: pre-wrap; word-break: break-word;
  line-height: 1.7;
}
</style>
