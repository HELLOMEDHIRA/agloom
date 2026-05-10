/**
 * Slash commands for the Ink CLI — `/help` output lines (also listed in README / docs).
 */

/** Lines shown when the user submits `/help` (also listed in README / docs). */
export const SLASH_HELP_LINES: string[] = [
  'Slash commands',
  '  /help              Show this list',
  '  /cancel            Cancel the current run (Ctrl+X)',
  '  /clear             Clear transcript + metrics notes',
  '  /model             Print active model (from runtime.config / metrics)',
  '  /diag              Toggle Python stderr log pane',
  '  /stats             Toggle right-hand metrics sidebar',
  '  /feedback <1-5>   Rate the last completed turn',
  '  /exit, /quit       Shutdown agloom-runtime and exit',
  '',
  'Many AGP responses (config applied, feedback.scored, sessions list, …)',
  'appear under “Wire notes” in the metrics sidebar.',
]
