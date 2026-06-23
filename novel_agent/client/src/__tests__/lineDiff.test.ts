import { describe, it, expect } from 'vitest'
import {
  buildLineDiffRows,
  charHighlightsToLineNumbers,
  computeChangedLineNumbers,
} from '@/utils/lineDiff'

describe('lineDiff', () => {
  it('computeChangedLineNumbers ignores unchanged prefix after insertion', () => {
    const oldText = 'line1\nline2\nline3'
    const newText = 'inserted\nline1\nline2\nline3'
    expect(computeChangedLineNumbers(oldText, newText)).toEqual([0])
  })

  it('computeChangedLineNumbers marks only modified lines', () => {
    const oldText = 'a\nb\nc'
    const newText = 'a\nB\nc'
    expect(computeChangedLineNumbers(oldText, newText)).toEqual([1])
  })

  it('buildLineDiffRows aligns inserted line without false modifications', () => {
    const rows = buildLineDiffRows('a\nb', 'x\na\nb')
    expect(rows).toEqual([
      { type: 'added', old: '', new: 'x' },
      { type: 'same', old: 'a', new: 'a' },
      { type: 'same', old: 'b', new: 'b' },
    ])
  })

  it('charHighlightsToLineNumbers maps char ranges to line indices', () => {
    const content = '第一行\n第二行\n第三行'
    const highlights: [number, number][] = [[4, 7]]
    expect(charHighlightsToLineNumbers(content, highlights)).toEqual([1])
  })

  it('computeChangedLineNumbers returns all lines when old text is empty', () => {
    expect(computeChangedLineNumbers('', 'a\nb')).toEqual([0, 1])
  })
})
