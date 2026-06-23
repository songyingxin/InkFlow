export type DiffRow = {
  type: 'same' | 'added' | 'removed' | 'modified'
  old: string
  new: string
}

type LineOpcode = {
  tag: 'equal' | 'insert' | 'delete' | 'replace'
  i1: number
  i2: number
  j1: number
  j2: number
}

function getLineOpcodes(oldLines: string[], newLines: string[]): LineOpcode[] {
  const n = oldLines.length
  const m = newLines.length
  const dp: number[][] = Array.from({ length: n + 1 }, () => Array(m + 1).fill(0))

  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      if (oldLines[i] === newLines[j]) {
        dp[i][j] = dp[i + 1][j + 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1])
      }
    }
  }

  type RawOp = { tag: 'equal' | 'insert' | 'delete'; i: number; j: number }
  const raw: RawOp[] = []
  let i = 0
  let j = 0
  while (i < n || j < m) {
    if (i < n && j < m && oldLines[i] === newLines[j]) {
      raw.push({ tag: 'equal', i, j })
      i += 1
      j += 1
    } else if (j < m && (i >= n || dp[i][j + 1] >= dp[i + 1][j])) {
      raw.push({ tag: 'insert', i, j })
      j += 1
    } else {
      raw.push({ tag: 'delete', i, j })
      i += 1
    }
  }

  const opcodes: LineOpcode[] = []
  let idx = 0
  while (idx < raw.length) {
    const tag = raw[idx].tag
    let end = idx + 1
    while (end < raw.length && raw[end].tag === tag) end += 1

    if (tag === 'equal') {
      opcodes.push({
        tag: 'equal',
        i1: raw[idx].i,
        i2: raw[end - 1].i + 1,
        j1: raw[idx].j,
        j2: raw[end - 1].j + 1,
      })
    } else if (tag === 'insert') {
      opcodes.push({
        tag: 'insert',
        i1: raw[idx].i,
        i2: raw[idx].i,
        j1: raw[idx].j,
        j2: raw[end - 1].j + 1,
      })
    } else {
      opcodes.push({
        tag: 'delete',
        i1: raw[idx].i,
        i2: raw[end - 1].i + 1,
        j1: raw[idx].j,
        j2: raw[idx].j,
      })
    }
    idx = end
  }

  const merged: LineOpcode[] = []
  for (const op of opcodes) {
    const prev = merged[merged.length - 1]
    if (prev && prev.tag === 'delete' && op.tag === 'insert') {
      merged[merged.length - 1] = {
        tag: 'replace',
        i1: prev.i1,
        i2: prev.i2,
        j1: op.j1,
        j2: op.j2,
      }
    } else if (prev && prev.tag === 'insert' && op.tag === 'delete') {
      merged[merged.length - 1] = {
        tag: 'replace',
        i1: op.i1,
        i2: op.i2,
        j1: prev.j1,
        j2: prev.j2,
      }
    } else {
      merged.push(op)
    }
  }
  return merged
}

export function charHighlightsToLineNumbers(
  content: string,
  highlights: [number, number][]
): number[] {
  if (!highlights.length) return []
  const lines = content.split('\n')
  const lineSet = new Set<number>()
  let charIdx = 0
  for (let i = 0; i < lines.length; i++) {
    const lineStart = charIdx
    const lineEnd = charIdx + lines[i].length
    for (const [hs, he] of highlights) {
      if (hs < lineEnd && he > lineStart) {
        lineSet.add(i)
        break
      }
    }
    charIdx = lineEnd + 1
  }
  return [...lineSet].sort((a, b) => a - b)
}

export function computeChangedLineNumbers(oldText: string, newText: string): number[] {
  if (!oldText) {
    if (!newText) return []
    return newText.split('\n').map((_, i) => i)
  }
  if (oldText === newText) return []

  const newLines = newText.split('\n')
  const opcodes = getLineOpcodes(oldText.split('\n'), newLines)
  const changed = new Set<number>()
  for (const op of opcodes) {
    if (op.tag === 'insert' || op.tag === 'replace') {
      for (let j = op.j1; j < op.j2; j++) changed.add(j)
    }
  }
  return [...changed].sort((a, b) => a - b)
}

export function buildLineDiffRows(oldText: string, newText: string): DiffRow[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  const opcodes = getLineOpcodes(oldLines, newLines)
  const rows: DiffRow[] = []

  for (const op of opcodes) {
    if (op.tag === 'equal') {
      for (let k = 0; k < op.i2 - op.i1; k++) {
        rows.push({
          type: 'same',
          old: oldLines[op.i1 + k],
          new: newLines[op.j1 + k],
        })
      }
    } else if (op.tag === 'delete') {
      for (let idx = op.i1; idx < op.i2; idx++) {
        rows.push({ type: 'removed', old: oldLines[idx], new: '' })
      }
    } else if (op.tag === 'insert') {
      for (let idx = op.j1; idx < op.j2; idx++) {
        rows.push({ type: 'added', old: '', new: newLines[idx] })
      }
    } else {
      const delCount = op.i2 - op.i1
      const insCount = op.j2 - op.j1
      const maxCount = Math.max(delCount, insCount)
      for (let k = 0; k < maxCount; k++) {
        const oldLine = k < delCount ? oldLines[op.i1 + k] : ''
        const newLine = k < insCount ? newLines[op.j1 + k] : ''
        if (oldLine === newLine) {
          rows.push({ type: 'same', old: oldLine, new: newLine })
        } else if (!oldLine) {
          rows.push({ type: 'added', old: '', new: newLine })
        } else if (!newLine) {
          rows.push({ type: 'removed', old: oldLine, new: '' })
        } else {
          rows.push({ type: 'modified', old: oldLine, new: newLine })
        }
      }
    }
  }
  return rows
}
