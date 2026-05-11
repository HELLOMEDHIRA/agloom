/**
 * Slash commands for the Ink CLI — `/help` output lines (also listed in README / docs).
 */

/** Short hints keyed by command prefix (used by InputBar autocomplete overlay). */
export const SLASH_HINTS: Record<string, string> = {
  '/help': 'Show slash commands',
  '/cancel': 'Cancel the current run (Ctrl+X)',
  '/clear': 'Clear transcript + metrics notes',
  '/model': 'Print active model from runtime',
  '/memory': 'Session memory: /memory clear',
  '/cost': 'Token/cost breakdown (wire notes + metrics history)',
  '/pattern': 'Set routing pattern via command.config.set',
  '/temperature': 'Set sampling temperature',
  '/system': 'Set system prompt (inline text)',
  '/session': 'List sessions: /session list',
  '/diag': 'Toggle Python stderr log pane',
  '/stats': 'Toggle metrics sidebar',
  '/tools': 'Toggle expand/collapse for all tools in the current turn (same as t / Ctrl+T)',
  '/budget': 'Raise session caps: /budget raise --tokens N  /  --usd N',
  '/feedback': 'Rate last turn /feedback <1-5>',
  '/save': 'Export transcript /save <path.md>',
  '/exit': 'Shutdown runtime and exit',
  '/quit': 'Shutdown runtime and exit',
}

/** Lines shown when the user submits `/help` (also listed in README / docs). */
export const SLASH_HELP_LINES: string[] = [
  'Slash commands',
  '  /help              Show this list',
  '  /cancel            Cancel the current run (Ctrl+X)',
  '  /clear             Clear transcript + metrics notes',
  '  /model             Print active model (from runtime.config / metrics)',
  '  /memory clear      Clear short-term session memory (current thread)',
  '  /cost              Token + cost summary and recent metric slices',
  '  /pattern <name>    Bias routing (AGP command.config.set)',
  '  /temperature <n>   Sampling temperature',
  '  /system <text>     System prompt (inline)',
  '  /session list      List stored session ids (requires --store)',
  '  /diag              Toggle Python stderr log pane',
  '  /stats             Toggle right-hand metrics sidebar',
  '  /tools             Toggle tool rows expand/collapse for the current turn (t / Ctrl+T)',
  '  /budget raise …  Raise token/USD caps (command.config.set); e.g. --tokens 200000 --usd 10',
  '  /feedback <1-5>   Rate the last completed turn',
  '  /save <path>       Write transcript (Markdown) to disk',
  '  /exit, /quit       Shutdown agloom-runtime and exit',
  '',
  'Many AGP responses (config applied, feedback.scored, sessions list, …)',
  'appear under “Wire notes” in the metrics sidebar.',
]
