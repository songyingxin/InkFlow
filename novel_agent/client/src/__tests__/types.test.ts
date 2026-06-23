/**
 * 类型与常量测试
 *
 * 验证前端类型定义和常量与后端的一致性：
 * - FIELD_LABELS 覆盖所有后端字段
 * - FIELD_TITLES 覆盖所有后端字段
 * - SIDEBAR_FIELDS 配置正确
 * - PLACEHOLDER_DEFAULTS 包含所有占位符
 * - SseEvent 类型完整性
 */

import { describe, it, expect } from 'vitest'
import {
  FIELD_LABELS,
  FIELD_TITLES,
  SIDEBAR_FIELDS,
  PLACEHOLDER_DEFAULTS,
} from '@/types'
import type { Book, Chapter, NovelState, ChatMessage, SseEvent, ContentSnapshot } from '@/types'

const BACKEND_FIELDS = [
  'outline_historical_md_content',
  'outline_future_md_content',
  'settings_md_content',
  'characters_md_content',
  'relationships_md_content',
  'foreshadowing_md_content',
]

describe('FIELD_LABELS', () => {
  it('covers all backend fields', () => {
    for (const field of BACKEND_FIELDS) {
      expect(FIELD_LABELS[field]).toBeDefined()
      expect(FIELD_LABELS[field].length).toBeGreaterThan(0)
    }
  })

  it('has no extra fields beyond backend fields', () => {
    const labelKeys = Object.keys(FIELD_LABELS)
    for (const key of labelKeys) {
      expect(BACKEND_FIELDS).toContain(key)
    }
  })

  it('all labels are Chinese', () => {
    for (const label of Object.values(FIELD_LABELS)) {
      expect(/[\u4e00-\u9fff]/.test(label)).toBe(true)
    }
  })
})

describe('FIELD_TITLES', () => {
  it('covers all backend fields plus title', () => {
    const expectedKeys = [...BACKEND_FIELDS, 'title']
    for (const key of expectedKeys) {
      expect(FIELD_TITLES[key]).toBeDefined()
    }
  })

  it('all titles start with 编辑', () => {
    for (const title of Object.values(FIELD_TITLES)) {
      expect(title.startsWith('编辑')).toBe(true)
    }
  })
})

describe('SIDEBAR_FIELDS', () => {
  it('has exactly 6 entries', () => {
    expect(SIDEBAR_FIELDS.length).toBe(6)
  })

  it('each entry has required properties', () => {
    for (const sf of SIDEBAR_FIELDS) {
      expect(sf.field).toBeDefined()
      expect(sf.icon).toBeDefined()
      expect(sf.label).toBeDefined()
      expect(sf.genFn).toBeDefined()
    }
  })

  it('all fields are backend fields', () => {
    for (const sf of SIDEBAR_FIELDS) {
      expect(BACKEND_FIELDS).toContain(sf.field)
    }
  })

  it('outline fields have genFn set to generateOutline', () => {
    const outlineFields = SIDEBAR_FIELDS.filter(sf => sf.field.includes('outline'))
    for (const sf of outlineFields) {
      expect(sf.genFn).toBe('generateOutline')
    }
  })

  it('non-outline fields have genFn set to null', () => {
    const nonOutlineFields = SIDEBAR_FIELDS.filter(sf => !sf.field.includes('outline'))
    for (const sf of nonOutlineFields) {
      expect(sf.genFn).toBeNull()
    }
  })

  it('no duplicate fields', () => {
    const fields = SIDEBAR_FIELDS.map(sf => sf.field)
    expect(new Set(fields).size).toBe(fields.length)
  })
})

describe('PLACEHOLDER_DEFAULTS', () => {
  it('contains all expected placeholders', () => {
    const expected = [
      '暂无大纲', '暂无历史大纲', '暂无未来大纲',
      '暂无设定', '暂无角色', '暂无关系图谱', '暂无伏笔',
    ]
    expect(PLACEHOLDER_DEFAULTS).toEqual(expected)
  })

  it('has 7 entries', () => {
    expect(PLACEHOLDER_DEFAULTS.length).toBe(7)
  })
})

describe('Type interfaces', () => {
  it('Book interface is compatible', () => {
    const book: Book = { name: 'test', title: '测试', total_chapters: 5 }
    expect(book.name).toBe('test')
    expect(book.total_chapters).toBe(5)
  })

  it('Chapter interface is compatible', () => {
    const chapter: Chapter = { idx: 1, title: '第一章', is_written: true }
    expect(chapter.idx).toBe(1)
    expect(chapter.is_written).toBe(true)
  })

  it('Chapter with optional fields', () => {
    const chapter: Chapter = {
      idx: 2, title: '第二章', is_written: false,
      content: '内容', content_summary: '摘要',
    }
    expect(chapter.content).toBe('内容')
  })

  it('ChatMessage interface', () => {
    const msg: ChatMessage = { role: 'user', content: '你好' }
    expect(msg.role).toBe('user')
  })

  it('ChatMessage with thinking', () => {
    const msg: ChatMessage = { role: 'assistant', content: '回复', thinking: '思考过程' }
    expect(msg.thinking).toBe('思考过程')
  })

  it('SseEvent token type', () => {
    const evt: SseEvent = { type: 'token', token: '你好' }
    expect(evt.type).toBe('token')
    expect(evt.token).toBe('你好')
  })

  it('SseEvent error type', () => {
    const evt: SseEvent = { type: 'error', error: '出错了' }
    expect(evt.type).toBe('error')
  })

  it('SseEvent interrupt type', () => {
    const evt: SseEvent = { type: 'interrupt', interrupt: { message: '确认？' } }
    expect(evt.interrupt?.message).toBe('确认？')
  })

  it('SseEvent done type', () => {
    const evt: SseEvent = { type: 'done' }
    expect(evt.type).toBe('done')
  })

  it('ContentSnapshot interface', () => {
    const snap: ContentSnapshot = {
      field: 'settings_md_content',
      chapterIdx: null,
      title: '',
      content: '设定内容',
      label: '生成',
    }
    expect(snap.field).toBe('settings_md_content')
  })

  it('NovelState interface is compatible', () => {
    const state: NovelState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 3 },
      outline: { title: '测试小说', chapters: [] },
      chapters: [],
      messages: [],
    }
    expect(state.current_book_name).toBe('测试')
  })

  it('NovelState with optional field content', () => {
    const state: NovelState = {
      current_book_name: '测试',
      has_outline: true,
      meta: { title: '测试小说', total_chapters: 0 },
      outline: null,
      chapters: [],
      messages: [],
      settings_md_content: '设定内容',
      characters_md_content: '角色内容',
      outline_historical_md_content: '历史大纲',
      outline_future_md_content: '未来大纲',
      relationships_md_content: '关系图谱',
      foreshadowing_md_content: '伏笔清单',
    }
    expect(state.settings_md_content).toBe('设定内容')
    expect(state.outline_historical_md_content).toBe('历史大纲')
  })

  it('NovelState with null outline', () => {
    const state: NovelState = {
      current_book_name: '测试',
      has_outline: false,
      meta: { title: '测试', total_chapters: 0 },
      outline: null,
      chapters: [],
      messages: [],
    }
    expect(state.outline).toBeNull()
  })
})

describe('FIELD_LABELS completeness', () => {
  it('has exactly 6 entries', () => {
    expect(Object.keys(FIELD_LABELS).length).toBe(6)
  })

  it('all values are unique', () => {
    const values = Object.values(FIELD_LABELS)
    expect(new Set(values).size).toBe(values.length)
  })
})

describe('FIELD_TITLES completeness', () => {
  it('has exactly 7 entries (6 fields + title)', () => {
    expect(Object.keys(FIELD_TITLES).length).toBe(7)
  })
})

describe('SIDEBAR_FIELDS ordering', () => {
  it('historical outline is first', () => {
    expect(SIDEBAR_FIELDS[0].field).toBe('outline_historical_md_content')
  })

  it('foreshadowing is last', () => {
    expect(SIDEBAR_FIELDS[5].field).toBe('foreshadowing_md_content')
  })
})

describe('SseEvent additional types', () => {
  it('SseEvent generate_start type', () => {
    const evt: SseEvent = { type: 'generate_start', target: 'settings_md_content' }
    expect(evt.type).toBe('generate_start')
    expect(evt.target).toBe('settings_md_content')
  })

  it('SseEvent generate_token type', () => {
    const evt: SseEvent = { type: 'generate_token', target: 'settings_md_content', token: '新' }
    expect(evt.type).toBe('generate_token')
  })

  it('SseEvent generate_done type', () => {
    const evt: SseEvent = { type: 'generate_done' }
    expect(evt.type).toBe('generate_done')
  })

  it('SseEvent plan_replan type', () => {
    const evt: SseEvent = { type: 'plan_replan', reason: '失败' }
    expect(evt.type).toBe('plan_replan')
  })
})
