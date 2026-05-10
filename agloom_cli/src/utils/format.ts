/**
 * Shared formatting helpers for the agloom CLI terminal UI.
 */

/** Truncate a string to `max` chars, appending `…` if cut. */
export function truncate(s: string, max: number): string {
  if (!s) return ''
  const clean = s.replace(/\s+/g, ' ').trim()
  return clean.length <= max ? clean : clean.slice(0, max - 1) + '…'
}

/** Render a duration in milliseconds as a human-friendly string. */
export function fmtDuration(ms: number | undefined): string {
  if (ms === undefined) return ''
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60_000)}m${Math.floor((ms % 60_000) / 1000)}s`
}

/** Format a token count with a K suffix for large numbers. */
export function fmtTokens(n: number): string {
  if (n < 1000) return `${n}`
  return `${(n / 1000).toFixed(1)}k`
}

/** Compact USD for telemetry sidebars. */
export function fmtUsd(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '$0'
  if (n < 0.01) return `$${n.toFixed(4)}`
  return `$${n.toFixed(3)}`
}

/** Shorten a long id for narrow columns (middle ellipsis). */
export function shortenMiddle(s: string, max: number): string {
  if (s.length <= max) return s
  const inner = max - 1
  const left = Math.ceil(inner / 2)
  const right = Math.floor(inner / 2)
  return `${s.slice(0, left)}…${s.slice(s.length - right)}`
}

/** Render a JSON args object as a compact one-line string. */
export function fmtArgs(args: Record<string, unknown>, maxLen = 60): string {
  try {
    const s = JSON.stringify(args)
    return truncate(s, maxLen)
  } catch {
    return '{…}'
  }
}

/** Strip leading/trailing blank lines from a multi-line string. */
export function trimLines(s: string): string {
  return s.replace(/^\n+/, '').replace(/\n+$/, '')
}

/**
 * Very light markdown → plain text renderer for terminal output.
 * Handles the most common constructs without pulling in a heavy parser.
 * For richer rendering, swap this out for a proper markdown-to-terminal lib.
 */
export function renderMarkdown(md: string, termWidth = 80): string {
  return md
    .split('\n')
    .map((line) => {
      // Headings: # → bold label
      const heading = /^(#{1,6})\s+(.+)$/.exec(line)
      if (heading) return `\x1b[1m${heading[2]}\x1b[0m`

      // Horizontal rule
      if (/^[-*_]{3,}$/.test(line.trim())) return '─'.repeat(Math.min(termWidth, 60))

      // Unordered list
      const bullet = /^(\s*)[-*+]\s+(.+)$/.exec(line)
      if (bullet) return `${bullet[1]}• ${bullet[2]}`

      // Ordered list
      const ordered = /^(\s*)\d+\.\s+(.+)$/.exec(line)
      if (ordered) return `${ordered[1]}  ${ordered[2]}`

      // Blockquote
      const quote = /^>\s+(.+)$/.exec(line)
      if (quote) return `\x1b[2m│ ${quote[1]}\x1b[0m`

      // Inline bold **text** or __text__
      line = line.replace(/\*\*(.+?)\*\*|__(.+?)__/g, (_m, a, b) => `\x1b[1m${a ?? b}\x1b[0m`)

      // Inline italic *text* or _text_
      line = line.replace(/\*(.+?)\*|_(.+?)_/g, (_m, a, b) => `\x1b[3m${a ?? b}\x1b[0m`)

      // Inline code `text`
      line = line.replace(/`([^`]+)`/g, (_m, code) => `\x1b[7m ${code} \x1b[0m`)

      return line
    })
    .join('\n')
}

/** Produce a coloured status badge string (no Ink dependency). */
export function statusBadge(status: string): string {
  switch (status) {
    case 'running':
      return '\x1b[33mrunning\x1b[0m'
    case 'thinking':
      return '\x1b[35mthinking\x1b[0m'
    case 'hitl':
      return '\x1b[31mwaiting\x1b[0m'
    case 'error':
      return '\x1b[31merror\x1b[0m'
    case 'exited':
      return '\x1b[90mexited\x1b[0m'
    default:
      return '\x1b[32midle\x1b[0m'
  }
}
