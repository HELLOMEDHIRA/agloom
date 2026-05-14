/** Terminal / Ink key detection helpers (Windows vs VT differences). */

/** True for Ctrl+Y (expand thinking). Ink often passes `y` + `ctrl`; Windows/consoles may send only ASCII 25 (`\\x19`) without `ctrl`. */
export const isCtrlY = (input: string, key: { ctrl?: boolean }): boolean => {
  const ch = input
  if (ch === '\x19' || ch === '\u0019') return true
  if (!key.ctrl) return false
  return ch === 'y' || ch === 'Y' || ch === '\x19' || ch === '\u0019'
}
