<template>
  <div class="md-editor">
    <div class="md-editor-header">
      <span class="md-editor-title">{{ title }}</span>
      <div class="md-editor-actions">
        <button
          v-if="showModeBtns"
          class="md-mode-btn"
          :class="{ active: !previewMode }"
          @click="$emit('switchMode', 'edit')"
        >编辑</button>
        <button
          v-if="showModeBtns"
          class="md-mode-btn"
          :class="{ active: previewMode }"
          @click="$emit('switchMode', 'preview')"
        >预览</button>
        <button class="fe-btn" :disabled="!canUndo" @click="$emit('undo')" title="撤销" aria-label="撤销">↩</button>
        <button class="fe-btn" :disabled="!canRedo" @click="$emit('redo')" title="重做" aria-label="重做">↪</button>
        <button
          v-if="hasHighlights && !diffMode"
          class="fe-btn fe-btn-diff"
          @click="diffMode = true"
          title="对比视图"
        >◀▶</button>
        <button
          v-if="diffMode"
          class="fe-btn fe-btn-diff active"
          @click="diffMode = false"
          title="退出对比"
        >◀▶</button>
        <button
          v-if="generating"
          class="fe-btn fe-btn-stop"
          @click="$emit('stop')"
        >■ 停止</button>
        <button
          class="fe-btn fe-btn-save"
          :disabled="saving"
          @click="$emit('save')"
          title="保存 (Ctrl+S)"
        >{{ saving ? '保存中...' : '保存' }}</button>
      </div>
    </div>

    <input
      v-if="showChapterTitle"
      class="fe-input chapter-title-input"
      :value="chapterTitle"
      placeholder="章节标题"
      @input="$emit('update:chapterTitle', ($event.target as HTMLInputElement).value)"
    />

    <div v-if="!previewMode" class="md-editor-shell">
      <div class="md-editor-inner">
        <div class="md-toolbar">
          <button class="md-tb-btn" title="一级标题" @click="insert('# ')">H1</button>
          <button class="md-tb-btn" title="二级标题" @click="insert('## ')">H2</button>
          <button class="md-tb-btn" title="三级标题" @click="insert('### ')">H3</button>
          <span class="md-tb-sep" />
          <button class="md-tb-btn" title="加粗" @click="wrap('**')"><b>B</b></button>
          <button class="md-tb-btn" title="斜体" @click="wrap('*')"><i>I</i></button>
          <span class="md-tb-sep" />
          <button class="md-tb-btn" title="引用" aria-label="引用" @click="insert('> ')">"</button>
          <button class="md-tb-btn" title="无序列表" aria-label="无序列表" @click="insert('- ')">-</button>
          <button class="md-tb-btn" title="有序列表" aria-label="有序列表" @click="insert('1. ')">1.</button>
          <span class="md-tb-sep" />
          <button class="md-tb-btn" title="链接" aria-label="插入链接" @click="insert('[文本](链接)')">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6.5 9.5a3 3 0 0 0 4.24 0l2-2a3 3 0 0 0-4.24-4.24l-1 1" />
              <path d="M9.5 6.5a3 3 0 0 0-4.24 0l-2 2a3 3 0 0 0 4.24 4.24l1-1" />
            </svg>
          </button>
          <button class="md-tb-btn" title="分割线" aria-label="分割线" @click="insert('\n---\n')">—</button>
        </div>
        <div class="md-editor-scrollarea" ref="scrollAreaRef">
          <div
            v-if="hasHighlights"
            class="md-diff-line-bg"
            ref="lineBgRef"
          >
            <div
              v-for="line in diffGutterLines"
              :key="line.idx"
              class="md-diff-line-bg-row"
              :class="{ changed: line.changed }"
            />
          </div>
          <div
            v-if="hasHighlights"
            class="md-diff-gutter"
            ref="gutterRef"
          >
            <div
              v-for="line in diffGutterLines"
              :key="line.idx"
              class="md-diff-gutter-line"
              :class="{ changed: line.changed }"
              @click="line.changed && jumpToNextChange(line.idx)"
            />
          </div>
          <textarea
            ref="textareaRef"
            class="md-textarea"
            :class="{ streaming: streaming, 'has-highlights': hasHighlights }"
            :value="content"
            :placeholder="placeholder"
            @input="onInput"
            @scroll="syncScroll"
          />
        </div>
      </div>
    </div>

    <div v-else-if="diffMode" class="md-diff-shell">
      <div class="md-diff-pane">
        <div class="md-diff-pane-header">原文</div>
        <div class="md-diff-pane-body">
          <div
            v-for="(line, i) in diffLines"
            :key="'o' + i"
            class="md-diff-line"
            :class="line.type"
          >
            <span class="md-diff-line-num">{{ i + 1 }}</span>
            <span class="md-diff-line-text">{{ line.old }}</span>
          </div>
        </div>
      </div>
      <div class="md-diff-pane">
        <div class="md-diff-pane-header">当前</div>
        <div class="md-diff-pane-body">
          <div
            v-for="(line, i) in diffLines"
            :key="'n' + i"
            class="md-diff-line"
            :class="line.type"
          >
            <span class="md-diff-line-num">{{ i + 1 }}</span>
            <span class="md-diff-line-text">{{ line.new }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="md-preview-shell">
      <div class="md-preview-inner">
        <div class="md-preview-panel" v-html="renderedMarkdown" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { marked } from 'marked'
import { buildLineDiffRows, computeChangedLineNumbers } from '@/utils/lineDiff'

const props = withDefaults(defineProps<{
  title: string
  content: string
  chapterTitle?: string
  showChapterTitle?: boolean
  showModeBtns?: boolean
  previewMode?: boolean
  placeholder?: string
  generating?: boolean
  saving?: boolean
  streaming?: boolean
  canUndo?: boolean
  canRedo?: boolean
  highlights?: number[]
  preEditContent?: string
}>(), {
  showChapterTitle: false,
  showModeBtns: true,
  previewMode: false,
  placeholder: '支持 Markdown 语法...',
  generating: false,
  saving: false,
  streaming: false,
  canUndo: false,
  canRedo: false,
})

const emit = defineEmits<{
  'update:content': [value: string]
  'update:chapterTitle': [value: string]
  save: []
  stop: []
  undo: []
  redo: []
  switchMode: [mode: 'edit' | 'preview']
  updateHighlights: [highlights: number[]]
}>()

const textareaRef = ref<HTMLTextAreaElement>()
const scrollAreaRef = ref<HTMLDivElement>()
const gutterRef = ref<HTMLDivElement>()
const lineBgRef = ref<HTMLDivElement>()
const diffMode = ref(false)

const hasHighlights = computed(() => !!(props.highlights && props.highlights.length > 0))

const diffLines = computed(() =>
  buildLineDiffRows(props.preEditContent || '', props.content || '')
)

const diffGutterLines = computed(() => {
  if (!props.content || !props.highlights?.length) return []
  const lines = props.content.split('\n')
  const hl = new Set(props.highlights)
  return lines.map((_, i) => ({ idx: i, changed: hl.has(i) }))
})


function syncScroll() {
  const top = textareaRef.value?.scrollTop ?? 0
  if (gutterRef.value) gutterRef.value.scrollTop = top
  if (lineBgRef.value) lineBgRef.value.scrollTop = top
}

function onInput(e: Event) {
  applyContentChange((e.target as HTMLTextAreaElement).value)
}

function applyContentChange(newContent: string) {
  emit('update:content', newContent)
  if (props.preEditContent) {
    emit('updateHighlights', computeChangedLineNumbers(props.preEditContent, newContent))
  }
}

function jumpToNextChange(currentLineIdx: number) {
  const ta = textareaRef.value
  if (!ta || !props.highlights?.length || !props.content) return
  const lines = props.content.split('\n')
  const changedLineIndices = diffGutterLines.value
    .filter(l => l.changed)
    .map(l => l.idx)
  if (!changedLineIndices.length) return
  const nextIdx = changedLineIndices.find(i => i > currentLineIdx)
  const targetLine = nextIdx ?? changedLineIndices[0]
  let pos = 0
  for (let i = 0; i < targetLine; i++) pos += lines[i].length + 1
  ta.focus()
  ta.setSelectionRange(pos, pos)
  const lineH = 16 * 2.1
  ta.scrollTop = Math.max(0, targetLine * lineH - ta.clientHeight / 3)
}

const renderedMarkdown = computed(() => {
  if (!props.content) return '<p style="color:var(--text-faint);">暂无内容</p>'
  return marked.parse(props.content) as string
})

function insert(text: string) {
  const ta = textareaRef.value
  if (!ta) return
  const start = ta.selectionStart; const end = ta.selectionEnd
  const before = ta.value.substring(0, start); const after = ta.value.substring(end)
  const needNewline = before.length > 0 && !before.endsWith('\n') ? '\n' : ''
  const newValue = before + needNewline + text + after
  ta.value = newValue
  applyContentChange(newValue)
  ta.focus()
  const pos = start + needNewline.length + text.length
  ta.setSelectionRange(pos, pos)
}

function wrap(wrapper: string) {
  const ta = textareaRef.value
  if (!ta) return
  const start = ta.selectionStart; const end = ta.selectionEnd
  const selected = ta.value.substring(start, end)
  const replacement = selected ? wrapper + selected + wrapper : wrapper + '文本' + wrapper
  const newValue = ta.value.substring(0, start) + replacement + ta.value.substring(end)
  ta.value = newValue
  applyContentChange(newValue)
  ta.focus()
  if (selected) { ta.setSelectionRange(start + wrapper.length, end + wrapper.length) }
  else { const pos = start + wrapper.length + 2; ta.setSelectionRange(pos, pos) }
}

watch(() => props.streaming, (val) => {
  if (val && textareaRef.value) textareaRef.value.scrollTop = textareaRef.value.scrollHeight
})
</script>

<style scoped>
.md-editor {
  max-width: 800px; margin: 0 auto; width: 100%;
  display: flex; flex-direction: column; flex: 1; min-height: 0;
  animation: reveal-up 400ms var(--spring-slow) both;
}

.md-editor-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px; flex-wrap: wrap; gap: 10px;
}

.md-editor-title {
  font-family: 'Noto Serif SC', serif;
  font-size: 17px; font-weight: 700; color: var(--text-primary);
  display: flex; align-items: center; gap: 8px;
}

.md-editor-title::before {
  content: ''; display: inline-block;
  width: 3px; height: 16px; background: var(--accent); border-radius: 2px;
}

.md-editor-actions { display: flex; gap: 6px; align-items: center; }

.md-mode-btn {
  padding: 5px 14px; border-radius: var(--radius-sm);
  font-size: 12px; font-weight: 500;
  border: 1px solid var(--border); background: var(--bg-raised);
  color: var(--text-secondary); transition: all var(--spring-fast);
}

.md-mode-btn:hover { border-color: var(--accent); color: var(--accent); }

.md-mode-btn.active {
  background: var(--accent); color: var(--accent-on); border-color: var(--accent); font-weight: 600;
}

.chapter-title-input { margin-bottom: 10px; }

.md-editor-shell {
  background: var(--bg-raised); border: 1px solid var(--border);
  border-radius: var(--radius-lg); overflow: hidden;
  display: flex; flex-direction: column; flex: 1; min-height: 0;
  transition: border-color var(--spring-fast), box-shadow var(--spring-fast);
  box-shadow: var(--shadow-sm);
}

.md-editor-shell:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim), var(--shadow-sm);
}

.md-editor-inner {
  display: flex; flex-direction: column; flex: 1; min-height: 0;
}

.md-toolbar {
  display: flex; gap: 1px; padding: 8px 14px;
  background: var(--bg-surface); border-bottom: 1px solid var(--border);
  flex-wrap: wrap; align-items: center;
}

.md-tb-btn {
  width: 28px; height: 26px; border: none; background: none;
  color: var(--text-muted); border-radius: var(--radius-sm);
  font-size: 11px; display: flex; align-items: center; justify-content: center;
  transition: all var(--spring-fast);
  font-family: 'JetBrains Mono', monospace; font-weight: 600;
}

.md-tb-btn:hover { background: var(--bg-hover); color: var(--accent); }
.md-tb-btn:active { transform: scale(0.9); }

.md-tb-sep { width: 1px; height: 14px; background: var(--border); margin: 0 5px; }

.md-editor-scrollarea { position: relative; flex: 1; min-height: 0; display: flex; }

.md-diff-gutter {
  width: var(--diff-gutter-w); flex-shrink: 0;
  overflow: hidden;
  background: transparent;
  padding-top: 28px;
}

.md-diff-gutter-line {
  height: 2.1em;
  font-size: 16px;
  line-height: 1;
}

.md-diff-gutter-line.changed {
  background: var(--diff-bar);
  border-radius: 0 1px 1px 0;
  cursor: pointer;
  pointer-events: auto;
  position: relative;
}

.md-diff-gutter-line.changed:hover {
  background: var(--accent);
}

.md-diff-gutter-line.changed:hover::after {
  content: '▾';
  position: absolute;
  right: -1px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 8px;
  color: var(--accent-on);
  line-height: 1;
}

.md-diff-line-bg {
  position: absolute; inset: 0;
  pointer-events: none; z-index: 0;
  overflow: hidden;
  padding-top: 28px;
}

.md-diff-line-bg-row {
  height: 2.1em;
  font-size: 16px;
  line-height: 1;
}

.md-diff-line-bg-row.changed {
  background: var(--diff-bg);
}

.md-textarea {
  display: block; width: 100%; height: 100%;
  padding: 28px 32px; border: none; border-radius: 0;
  background: var(--bg-raised); color: var(--text-primary);
  font-size: 16px; outline: none; resize: none;
  font-family: 'Noto Serif SC', serif; line-height: 2.1;
  caret-color: var(--accent); position: relative; z-index: 1;
  flex: 1; min-width: 0;
}

.md-textarea.has-highlights {
  border-left: none;
  background: transparent;
}

.md-textarea::placeholder { color: var(--text-faint); }
.md-textarea::selection { background: rgba(var(--accent-rgb), 0.15); }

.md-textarea.streaming { animation: cursor-blink 0.8s step-end infinite; }

.md-preview-shell {
  background: var(--bg-raised); border: 1px solid var(--border);
  border-radius: var(--radius-lg); overflow: hidden;
  flex: 1; min-height: 0; display: flex; box-shadow: var(--shadow-sm);
}

.md-preview-inner {
  flex: 1; min-height: 0; overflow: hidden; display: flex;
}

.md-preview-panel {
  flex: 1; min-height: 0; overflow-y: auto;
  padding: 32px 36px; color: var(--text-primary);
  font-size: 16px; line-height: 2.1;
  font-family: 'Noto Serif SC', serif;
  animation: reveal-up 300ms var(--spring-medium) both;
}



.md-preview-panel :deep(h1) {
  font-family: 'Noto Serif SC', serif;
  font-size: 28px; font-weight: 700; margin: 0 0 16px;
  padding-bottom: 14px; border-bottom: 1px solid var(--border);
  color: var(--accent);
}

.md-preview-panel :deep(h2) {
  font-family: 'Noto Serif SC', serif;
  font-size: 22px; font-weight: 600; margin: 28px 0 10px; color: var(--text-primary);
}

.md-preview-panel :deep(h3) {
  font-family: 'Noto Serif SC', serif;
  font-size: 18px; font-weight: 600; margin: 20px 0 8px; color: var(--text-secondary);
}

.md-preview-panel :deep(p) { margin: 0 0 14px; }
.md-preview-panel :deep(ul), .md-preview-panel :deep(ol) { margin: 0 0 14px; padding-left: 24px; }
.md-preview-panel :deep(li) { margin-bottom: 5px; }
.md-preview-panel :deep(li::marker) { color: var(--accent); }

.md-preview-panel :deep(blockquote) {
  border-left: 3px solid var(--accent); padding: 12px 20px; margin: 0 0 16px;
  color: var(--text-secondary); background: var(--accent-dim);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0; font-style: italic;
}

.md-preview-panel :deep(code) {
  background: var(--bg-input); padding: 2px 7px; border-radius: 4px;
  font-size: 0.88em; font-family: 'JetBrains Mono', monospace;
  color: var(--accent-strong); border: 1px solid var(--border);
}

.md-preview-panel :deep(pre) {
  background: var(--bg-input); padding: 18px 22px; border-radius: var(--radius-md);
  overflow-x: auto; margin: 0 0 16px; border: 1px solid var(--border);
}

.md-preview-panel :deep(pre code) { background: none; padding: 0; border: none; color: var(--text-secondary); }

.md-preview-panel :deep(strong) { font-weight: 700; color: var(--text-primary); }
.md-preview-panel :deep(em) { font-style: italic; color: var(--accent); }
.md-preview-panel :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
.md-preview-panel :deep(a) { color: var(--accent); text-decoration: none; border-bottom: 1px solid var(--accent-dim); }
.md-preview-panel :deep(a:hover) { border-bottom-color: var(--accent); }

.fe-btn {
  padding: 6px 14px; border-radius: var(--radius-sm);
  font-size: 12px; font-weight: 500;
  border: 1px solid var(--border); background: var(--bg-raised);
  color: var(--text-secondary); transition: all var(--spring-fast);
}

.fe-btn:hover { border-color: var(--accent); background: var(--bg-hover); color: var(--accent); }
.fe-btn:active { transform: scale(0.96); }
.fe-btn:disabled { opacity: 0.35; cursor: not-allowed; transform: none; }

.fe-btn-save {
  background: var(--accent); color: var(--accent-on); border-color: var(--accent); font-weight: 600;
}

.fe-btn-save:hover { background: var(--accent-strong); border-color: var(--accent-strong); color: var(--accent-on); }

.fe-btn-diff {
  background: transparent; color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  font-size: 11px;
}
.fe-btn-diff:hover { border-color: var(--accent); color: var(--accent); }
.fe-btn-diff.active { background: var(--accent-dim); border-color: var(--accent); color: var(--accent); }

.md-diff-shell {
  display: flex;
  height: 100%;
  overflow: hidden;
}

.md-diff-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid var(--border-subtle);
}
.md-diff-pane:last-child { border-right: none; }

.md-diff-pane-header {
  padding: 8px 16px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-faint);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
}

.md-diff-pane-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.md-diff-line {
  display: flex;
  padding: 1px 12px;
  font-size: 13px;
  line-height: 1.7;
  font-family: 'Noto Serif SC', serif;
  border-left: 3px solid transparent;
}

.md-diff-line-num {
  width: 32px;
  flex-shrink: 0;
  color: var(--text-faint);
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
  text-align: right;
  padding-right: 8px;
  user-select: none;
}

.md-diff-line-text {
  flex: 1;
  white-space: pre-wrap;
  word-break: break-all;
}

.md-diff-line.same { color: var(--text-secondary); }
.md-diff-line.added { background: rgba(82, 122, 90, 0.08); border-left-color: var(--sage); color: var(--sage); }
.md-diff-line.removed { background: var(--rose-dim); border-left-color: var(--rose); color: var(--rose); text-decoration: line-through; opacity: 0.7; }
.md-diff-line.modified { background: var(--accent-dim); border-left-color: var(--accent); }

.fe-btn-stop {
  background: var(--rose-dim); color: var(--rose); border-color: transparent; font-weight: 600;
}

.fe-btn-stop:hover { background: var(--rose); color: #fff; }

.fe-input {
  width: 100%; padding: 14px 18px;
  border: 1px solid var(--border); border-radius: var(--radius-md);
  background: var(--bg-raised); color: var(--text-primary);
  font-size: 18px; font-weight: 700; outline: none;
  font-family: 'Noto Serif SC', serif;
  transition: all var(--spring-fast); caret-color: var(--accent);
}

.fe-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-dim); }
.fe-input::selection { background: rgba(var(--accent-rgb), 0.15); }
.fe-input::placeholder { color: var(--text-faint); font-weight: 400; }
</style>
