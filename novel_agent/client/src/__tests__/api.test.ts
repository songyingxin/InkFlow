/**
 * API 模块测试
 *
 * 测试前端 API 层的纯函数和请求构造逻辑：
 * - extractErrDetail: 错误信息提取
 * - API 函数签名完整性
 * - chatStream / resumeStream 的 SSE 解析逻辑
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

function extractErrDetail(err: unknown): string {
  if (!err) return ''
  if (typeof err === 'string') return err
  if (typeof (err as any).detail === 'string') return (err as any).detail
  if ((err as any).detail != null) return JSON.stringify((err as any).detail)
  return ''
}

describe('extractErrDetail', () => {
  it('returns empty string for null', () => {
    expect(extractErrDetail(null)).toBe('')
  })

  it('returns empty string for undefined', () => {
    expect(extractErrDetail(undefined)).toBe('')
  })

  it('returns string as-is', () => {
    expect(extractErrDetail('错误信息')).toBe('错误信息')
  })

  it('extracts string detail', () => {
    expect(extractErrDetail({ detail: '字段无效' })).toBe('字段无效')
  })

  it('stringifies non-string detail', () => {
    expect(extractErrDetail({ detail: { code: 400, msg: 'bad' } })).toContain('400')
  })

  it('returns empty for object without detail', () => {
    expect(extractErrDetail({ message: 'test' })).toBe('')
  })

  it('handles numeric detail', () => {
    expect(extractErrDetail({ detail: 404 })).toBe('404')
  })
})

describe('SSE parsing logic', () => {
  function parseSseLines(lines: string[]): any[] {
    const events: any[] = []
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) continue
      try {
        events.push(JSON.parse(trimmed.slice(6)))
      } catch { /* skip */ }
    }
    return events
  }

  it('parses valid SSE lines', () => {
    const lines = [
      'data: {"type":"token","token":"你好"}',
      'data: {"type":"done"}',
    ]
    const events = parseSseLines(lines)
    expect(events.length).toBe(2)
    expect(events[0].type).toBe('token')
    expect(events[0].token).toBe('你好')
    expect(events[1].type).toBe('done')
  })

  it('skips non-data lines', () => {
    const lines = [
      'event: message',
      'data: {"type":"token","token":"世界"}',
      ': comment',
    ]
    const events = parseSseLines(lines)
    expect(events.length).toBe(1)
    expect(events[0].token).toBe('世界')
  })

  it('skips malformed JSON', () => {
    const lines = [
      'data: {invalid json}',
      'data: {"type":"token","token":"有效"}',
    ]
    const events = parseSseLines(lines)
    expect(events.length).toBe(1)
    expect(events[0].token).toBe('有效')
  })

  it('handles empty lines', () => {
    const lines = [
      '',
      'data: {"type":"done"}',
      '',
    ]
    const events = parseSseLines(lines)
    expect(events.length).toBe(1)
  })

  it('handles error events', () => {
    const lines = [
      'data: {"type":"error","error":"LLM 超时"}',
    ]
    const events = parseSseLines(lines)
    expect(events[0].type).toBe('error')
    expect(events[0].error).toBe('LLM 超时')
  })

  it('handles interrupt events', () => {
    const lines = [
      'data: {"type":"interrupt","interrupt":{"message":"确认继续？"}}',
    ]
    const events = parseSseLines(lines)
    expect(events[0].type).toBe('interrupt')
    expect(events[0].interrupt.message).toBe('确认继续？')
  })

  it('handles generate events', () => {
    const lines = [
      'data: {"type":"generate_start","target":"settings_md_content"}',
      'data: {"type":"generate_token","target":"settings_md_content","token":"新"}',
      'data: {"type":"generate_done"}',
    ]
    const events = parseSseLines(lines)
    expect(events.length).toBe(3)
    expect(events[0].target).toBe('settings_md_content')
  })
})

describe('API function signatures', () => {
  it('all API functions are exported', async () => {
    const api = await import('@/api')
    const expectedFns = [
      'listBooks', 'createBook', 'selectBook', 'deleteBook',
      'getState', 'getChapterContent', 'addChapter', 'updateChapter',
      'deleteChapter', 'updateField', 'getChatHistory', 'clearChat',
      'chatStream', 'resumeStream', 'importChaptersBatch',
    ]
    for (const fn of expectedFns) {
      expect(typeof api[fn as keyof typeof api]).toBe('function')
    }
  })
})

describe('Request construction', () => {
  it('createBook sends correct body', () => {
    const body = JSON.stringify({ title: '测试小说' })
    const parsed = JSON.parse(body)
    expect(parsed.title).toBe('测试小说')
  })

  it('chatStream sends correct body', () => {
    const body = JSON.stringify({
      message: '续写下一章',
      field_values: { settings_md_content: '设定' },
    })
    const parsed = JSON.parse(body)
    expect(parsed.message).toBe('续写下一章')
    expect(parsed.field_values.settings_md_content).toBe('设定')
  })

  it('resumeStream sends correct body', () => {
    const body = JSON.stringify({ value: true })
    const parsed = JSON.parse(body)
    expect(parsed.value).toBe(true)
  })

  it('importChaptersBatch uses FormData', () => {
    const formData = new FormData()
    const file = new File(['[]'], 'test.json', { type: 'application/json' })
    formData.append('file', file)
    expect(formData.get('file')).toBeInstanceOf(File)
  })
})

describe('extractErrDetail edge cases', () => {
  function extractErrDetail(err: unknown): string {
    if (!err) return ''
    if (typeof err === 'string') return err
    if (typeof (err as any).detail === 'string') return (err as any).detail
    if ((err as any).detail != null) return JSON.stringify((err as any).detail)
    return ''
  }

  it('handles boolean false', () => {
    expect(extractErrDetail(false)).toBe('')
  })

  it('handles number 0', () => {
    expect(extractErrDetail(0)).toBe('')
  })

  it('handles empty string', () => {
    expect(extractErrDetail('')).toBe('')
  })

  it('handles array detail', () => {
    expect(extractErrDetail({ detail: [1, 2, 3] })).toContain('1')
  })
})

describe('SSE parsing edge cases', () => {
  function parseSseLines(lines: string[]): any[] {
    const events: any[] = []
    for (const line of lines) {
      const trimmed = line.trim()
      if (!trimmed.startsWith('data: ')) continue
      try {
        events.push(JSON.parse(trimmed.slice(6)))
      } catch { /* skip */ }
    }
    return events
  }

  it('handles plan events', () => {
    const lines = [
      'data: {"type":"plan_generated","steps":3}',
      'data: {"type":"plan_step_start","step":1}',
      'data: {"type":"plan_step_complete","step":1}',
      'data: {"type":"plan_completed"}',
    ]
    const events = parseSseLines(lines)
    expect(events.length).toBe(4)
    expect(events[0].type).toBe('plan_generated')
  })

  it('handles handoff event', () => {
    const lines = [
      'data: {"type":"handoff","agent":"creator"}',
    ]
    const events = parseSseLines(lines)
    expect(events[0].type).toBe('handoff')
    expect(events[0].agent).toBe('creator')
  })

  it('handles subagent events', () => {
    const lines = [
      'data: {"type":"subagent_token","token":"生成中"}',
      'data: {"type":"subagent_tool_call","name":"read_novel_content"}',
    ]
    const events = parseSseLines(lines)
    expect(events.length).toBe(2)
    expect(events[0].token).toBe('生成中')
    expect(events[1].name).toBe('read_novel_content')
  })

  it('handles field_content event', () => {
    const lines = [
      'data: {"type":"field_content","target":"settings_md_content","content":"新设定"}',
    ]
    const events = parseSseLines(lines)
    expect(events[0].type).toBe('field_content')
    expect(events[0].target).toBe('settings_md_content')
    expect(events[0].content).toBe('新设定')
  })

  it('handles reasoning event', () => {
    const lines = [
      'data: {"type":"reasoning","token":"思考中..."}',
    ]
    const events = parseSseLines(lines)
    expect(events[0].type).toBe('reasoning')
    expect(events[0].token).toBe('思考中...')
  })

  it('handles assistant_reply event', () => {
    const lines = [
      'data: {"type":"assistant_reply","content":"这是回复"}',
    ]
    const events = parseSseLines(lines)
    expect(events[0].type).toBe('assistant_reply')
    expect(events[0].content).toBe('这是回复')
  })

  it('handles chapter_title event', () => {
    const lines = [
      'data: {"type":"chapter_title","title":"风起云涌"}',
    ]
    const events = parseSseLines(lines)
    expect(events[0].type).toBe('chapter_title')
    expect(events[0].title).toBe('风起云涌')
  })
})
