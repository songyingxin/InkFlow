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
              <button class="sb-ch-import-btn" @click="$emit('showImport')" title="批量导入">
                <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2z"/><polyline points="14 2 10 2 10 8"/><line x1="10" y1="2" x2="8" y2="6"/>
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
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useEditorStore, useConfirmStore, useChatStore } from '@/stores'
import { SIDEBAR_FIELDS } from '@/types'
import type { Chapter } from '@/types'
import SbIcon from './SbIcon.vue'

const emit = defineEmits<{
  showImport: []
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
  editorStore.editingField = field
  editorStore.mdPreviewMode = false
  emit('fieldChanged')
}

async function loadChapter(idx: number) {
  try {
    await editorStore.loadChapter(idx)
    emit('fieldChanged')
  } catch (e: any) { console.error('Load chapter failed:', e) }
}

function addChapter() {
  editorStore.editingField = 'chapter_new'
  editorStore.activeChapterIdx = null
  editorStore.mdPreviewMode = false
  emit('fieldChanged')
}

async function deleteChapter(idx: number) {
  const ok = await confirmStore.confirm({
    title: '删除章节',
    desc: '确定删除第 ' + idx + ' 章？此操作不可恢复。',
    confirmText: '确认删除',
    variant: 'danger',
  })
  if (!ok) return
  try {
    await editorStore.removeChapter(idx)
    emit('fieldChanged')
    chatStore.loadHistory()
  } catch (e: any) { console.error('Delete chapter failed:', e) }
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

.sb-ch-import-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 24px; height: 24px;
  border: 1px solid var(--border); border-radius: var(--radius-sm);
  background: transparent; color: var(--text-muted);
  transition: all var(--spring-fast);
}

.sb-ch-import-btn:hover { border-color: var(--accent); color: var(--accent); }

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
</style>
