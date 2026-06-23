import type { Book, NovelState, ChatMessage, SseEvent } from '@/types'

const BASE = ''

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 10000)
  const signal = options?.signal
    ? AbortSignal.any([controller.signal, options.signal])
    : controller.signal
  try {
    const res = await fetch(BASE + url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      signal,
    })
    clearTimeout(timeout)
    if (!res.ok) {
      let err
      try { err = await res.json() } catch { /* ignore */ }
      throw new Error(extractErrDetail(err) || `请求失败: ${res.status}`)
    }
    return res.json()
  } catch (e: any) {
    clearTimeout(timeout)
    if (e.name === 'AbortError') throw new Error('请求超时，请确认后端是否已启动')
    throw e
  }
}

function extractErrDetail(err: unknown): string {
  if (!err) return ''
  if (typeof err === 'string') return err
  if (typeof (err as any).detail === 'string') return (err as any).detail
  if ((err as any).detail != null) return JSON.stringify((err as any).detail)
  return ''
}

async function* parseSseStream(res: Response): AsyncGenerator<SseEvent> {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let receivedDone = false

  while (true) {
    try {
      const result = await reader.read()
      if (result.done) { receivedDone = true; break }
      buffer += decoder.decode(result.value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()!

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data: ')) continue
        try {
          const evt: SseEvent = JSON.parse(trimmed.slice(6))
          if (evt.type === 'done') receivedDone = true
          yield evt
        } catch { /* skip malformed */ }
      }
    } catch (_e) {
      try { reader.cancel() } catch { /* ignore */ }
      if (!receivedDone) throw _e
      break
    }
  }
}

async function* postSseStream(
  url: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  const res = await fetch(BASE + url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    let err
    try { err = await res.json() } catch { /* ignore */ }
    throw new Error(extractErrDetail(err) || '请求失败')
  }

  yield* parseSseStream(res)
}

export function listBooks(): Promise<{ books: Book[] }> {
  return request('/api/books')
}

export function createBook(title: string): Promise<{ message: string; book: Book; state: NovelState }> {
  return request('/api/books/create', {
    method: 'POST',
    body: JSON.stringify({ title }),
  })
}

export function selectBook(name: string): Promise<{ message: string; book: Book; state: NovelState }> {
  return request('/api/books/select', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function deleteBook(name: string): Promise<{ message: string; books: Book[] }> {
  return request('/api/books/delete', {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
}

export function getState(): Promise<NovelState> {
  return request('/api/state')
}

export function getChapterContent(idx: number): Promise<{ idx: number; title: string; content: string }> {
  return request(`/api/chapters/content/${idx}`)
}

export function addChapter(title: string, content: string): Promise<{ message: string; chapter: any; state: NovelState }> {
  return request('/api/chapters/add', {
    method: 'POST',
    body: JSON.stringify({ title, content }),
  })
}

export function updateChapter(idx: number, title: string, content: string): Promise<{ message: string; state: NovelState }> {
  return request(`/api/chapters/update/${idx}`, {
    method: 'POST',
    body: JSON.stringify({ title, content }),
  })
}

export function deleteChapter(idx: number): Promise<{ message: string; state: NovelState }> {
  return request(`/api/chapters/delete/${idx}`, {
    method: 'DELETE',
  })
}

export function updateField(field: string, value: string): Promise<{ message: string; state: NovelState }> {
  return request('/api/fields/update', {
    method: 'POST',
    body: JSON.stringify({ field, value }),
  })
}

export function getChatHistory(rounds: number = 10): Promise<{ messages: ChatMessage[] }> {
  return request(`/api/chat/history?rounds=${rounds}`)
}

export function clearChat(): Promise<{ message: string }> {
  return request('/api/chat/clear', { method: 'POST' })
}

export async function* chatStream(
  message: string,
  fieldValues: Record<string, string>,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  yield* postSseStream('/api/chat/stream', { message, field_values: fieldValues }, signal)
}

export async function* resumeStream(
  value: boolean | string,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent> {
  yield* postSseStream('/api/chat/resume', { value }, signal)
}

export function importChaptersBatch(file: File): Promise<{ message: string; imported_count: number; state: NovelState }> {
  const formData = new FormData()
  formData.append('file', file)
  return request('/api/chapters/import-batch', {
    method: 'POST',
    body: formData,
    headers: {},
  })
}
