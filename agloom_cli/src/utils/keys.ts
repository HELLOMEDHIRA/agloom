/** Terminal / Ink key detection helpers (Windows vs VT differences). */

/** True for Ctrl+Y (expand thinking). Ink often passes `y`; some consoles send ASCII 25 (`\\x19`). */
export const isCtrlY = (input: string, key: { ctrl?: boolean }): boolean => {
  if (!key.ctrl) return false
  const ch = input
  return ch === 'y' || ch === 'Y' || ch === '\x19' || ch === '\u0019'
}
