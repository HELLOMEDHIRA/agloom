/**
 * Best-effort terminal cleanup after the TUI exits. Helps hosts that do not fully honour
 * alternate-screen teardown (leaving sidebar fragments above the shell prompt).
 */

export const resetTerminalForShell = (): void => {
  try {
    if (!process.stdout.isTTY) return
    process.stdout.write('\x1b[?1049l') // leave alternate screen (no-op if not active)
    process.stdout.write('\x1b[?25h') // show cursor
    process.stdout.write('\x1b[0m') // reset SGR
  } catch {
    /* ignore */
  }
}
