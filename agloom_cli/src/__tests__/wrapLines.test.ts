import { describe, expect, it } from '@jest/globals'
import { wrapTextLines } from '../utils/wrapLines.js'

describe('wrapTextLines', () => {
  it('wraps long lines at word boundaries', () => {
    const lines = wrapTextLines('hello world foo bar', 10)
    expect(lines).toEqual(['hello', 'world foo', 'bar'])
  })

  it('preserves explicit newlines', () => {
    const lines = wrapTextLines('line one\nline two', 40)
    expect(lines).toEqual(['line one', 'line two'])
  })

  it('returns one empty row for blank input', () => {
    expect(wrapTextLines('', 40)).toEqual([''])
  })
})
