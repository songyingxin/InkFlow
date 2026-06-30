export interface Book {
  name: string
  title: string
  total_chapters: number
  written_chapters?: number
  word_count?: number
  updated_at?: number
}

export interface Chapter {
  idx: number
  title: string
  content?: string
  content_summary?: string
  is_written: boolean
}

export interface NovelState {
  current_book_name: string
  has_outline: boolean
  meta: {
    title: string
    total_chapters: number
  }
  outline: {
    title: string
    chapters: Chapter[]
  } | null
  chapters: Chapter[]
  deleted_chapters?: number[]
  messages: ChatMessage[]
  settings_md_content?: string
  outline_future_md_content?: string
  characters_md_content?: string
  locations_md_content?: string
  relationships_md_content?: string
  foreshadowing_md_content?: string
}

export interface AgentActivityStep {
  kind: 'handoff' | 'tool' | 'plan'
  label: string
  agent?: string
  tool?: string
  status?: 'running' | 'done' | 'error'
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  thinking?: string
  activity?: AgentActivityStep[]
}

export interface DailySyncStatus {
  has_pending: boolean
  pending_chapters: number
  max_written_chapter: number
  chapter_from: number
  chapter_to: number
  last_daily_sync_date: string
  should_prompt: boolean
  daily_sync_enabled: boolean
}

export type SseEvent =
  | { type: 'token'; token: string }
  | { type: 'reasoning'; token: string }
  | { type: 'assistant_reply'; content: string; activity?: AgentActivityStep[] }
  | { type: 'agent_activity'; step: AgentActivityStep }
  | { type: 'task_complete'; summary?: string }
  | { type: 'chapter_title'; title: string; chapter_num?: number }
  | { type: 'generate_start'; target: string }
  | { type: 'generate_token'; target: string; token: string }
  | { type: 'generate_done'; target?: string; title?: string }
  | { type: 'generate_reset'; target: string }
  | { type: 'field_content'; target: string; content: string; highlights?: [number, number][] }
  | { type: 'interrupt'; interrupt: { message: string } }
  | { type: 'handoff'; agent: string }
  | { type: 'subagent_token'; token: string }
  | { type: 'subagent_tool_call'; name: string }
  | { type: 'plan_generated'; steps: number }
  | { type: 'plan_step_start'; step: number }
  | { type: 'plan_step_complete'; step: number }
  | { type: 'plan_completed' }
  | { type: 'plan_replan'; reason: string; name?: string }
  | { type: 'critic_review_start'; agent: string }
  | { type: 'critic_review_done'; success: boolean; summary?: string }
  | { type: 'daily_sync_start'; pending_chapters: number; chapter_from: number; chapter_to: number }
  | { type: 'daily_sync_done'; last_daily_sync_date: string; has_pending: boolean; steps?: Record<string, string> }
  | { type: 'state'; state: NovelState }
  | { type: 'error'; error: string }
  | { type: 'done' }

export interface FieldLabels {
  [key: string]: string
}

export const FIELD_LABELS: FieldLabels = {
  outline_future_md_content: '未来大纲',
  settings_md_content: '写作设定',
  characters_md_content: '角色档案',
  locations_md_content: '地点档案',
  relationships_md_content: '关系图谱',
  foreshadowing_md_content: '伏笔清单',
}

export const FIELD_TITLES: FieldLabels = {
  title: '编辑小说名',
  outline_future_md_content: '编辑未来大纲',
  settings_md_content: '编辑写作设定',
  characters_md_content: '编辑角色档案',
  locations_md_content: '编辑地点档案',
  relationships_md_content: '编辑关系图谱',
  foreshadowing_md_content: '编辑伏笔清单',
}

export const SIDEBAR_FIELDS = [
  { field: 'outline_future_md_content', icon: 'future', label: '未来大纲', genFn: 'generateOutline' },
  { field: 'settings_md_content', icon: 'settings', label: '写作设定', genFn: null },
  { field: 'characters_md_content', icon: 'characters', label: '角色档案', genFn: null },
  { field: 'locations_md_content', icon: 'locations', label: '地点档案', genFn: null },
  { field: 'relationships_md_content', icon: 'relationships', label: '关系图谱', genFn: null },
  { field: 'foreshadowing_md_content', icon: 'foreshadowing', label: '伏笔清单', genFn: null },
] as const

export interface ContentSnapshot {
  field: string
  chapterIdx: number | null
  title: string
  content: string
  label: string
}

export interface BackupItem {
  timestamp: string
  date: string
  time: string
  size: number
  preview: string
  hash: string
}

export interface BackupListResponse {
  chapter_idx: number
  current_hash: string
  backups: BackupItem[]
}

export interface BackupPreview {
  chapter_idx: number
  timestamp: string
  content: string
  size: number
  is_full: boolean
}

export const PLACEHOLDER_DEFAULTS = [
  '暂无大纲', '暂无未来大纲',
  '暂无设定', '暂无角色', '暂无地点', '暂无关系图谱', '暂无伏笔',
]
