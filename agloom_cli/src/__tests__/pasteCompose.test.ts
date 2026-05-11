import { splitPastedMultilineWhenSingleLineMode } from '../utils/pasteCompose'

describe('splitPastedMultilineWhenSingleLineMode', () => {
  it('returns null when multiline mode is on', () => {
    expect(splitPastedMultilineWhenSingleLineMode(true, 'a\nb')).toBeNull()
  })

  it('returns null when there are no newlines', () => {
    expect(splitPastedMultilineWhenSingleLineMode(false, 'hello')).toBeNull()
  })

  it('splits head lines and tail when pasting multiple lines', () => {
    expect(splitPastedMultilineWhenSingleLineMode(false, 'line1\nline2\ntail')).toEqual({
      headLines: ['line1', 'line2'],
      inputTail: 'tail',
    })
  })

  it('handles trailing newline (empty tail)', () => {
    expect(splitPastedMultilineWhenSingleLineMode(false, 'only\n')).toEqual({
      headLines: ['only'],
      inputTail: '',
    })
  })
})
