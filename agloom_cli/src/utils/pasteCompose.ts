/** Paste auto-detect for single-line compose (Tier 2 B1).
 * When `--multiline` / `AGLOOM_MULTILINE` is off, a single `onChange` can still deliver many lines (terminal bracketed paste or platform paste). Split into queued lines + tail for the current field so the existing multiline send path applies (`App.tsx` + blank Enter).
 */

export interface PastedMultilineSplit {
  /** Lines to append before the final segment (each becomes one queued line). */
  headLines: string[]
  /** Remainder kept in the single-line input (may be empty). */
  inputTail: string
}

/**
 * If multiline mode is off and `newValue` contains newlines, return how to split
 * the buffer; otherwise return `null` (caller should treat `newValue` as normal input).
 */
export function splitPastedMultilineWhenSingleLineMode(
  multilineOpt: boolean,
  newValue: string,
): PastedMultilineSplit | null {
  if (multilineOpt || !newValue.includes('\n')) return null
  const parts = newValue.split('\n')
  const inputTail = parts.pop() ?? ''
  return { headLines: parts, inputTail }
}
