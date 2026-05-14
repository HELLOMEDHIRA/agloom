/** Shared formatting helpers for the agloom CLI terminal UI. */

import { highlight } from 'cli-highlight'

/** Truncate a string to `max` chars, appending `…` if cut. */
export const truncate = (s: string, max: number): string => {
  if (!s) return ''
  const clean = s.replace(/\s+/g, ' ').trim()
  return clean.length <= max ? clean : `${clean.slice(0, max - 1)}…`
}

/** Render a duration in milliseconds as a human-friendly string. */
export const fmtDuration = (ms: number | undefined): string => {
  if (ms === undefined) return ''
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60_000)}m${Math.floor((ms % 60_000) / 1000)}s`
}

/** Format a token count with a K suffix for large numbers. */
export const fmtTokens = (n: number): string => {
  if (n < 1000) return `${n}`
  return `${(n / 1000).toFixed(1)}k`
}

/** Compact USD for telemetry sidebars (includes sub-cent estimates). */
export const fmtUsd = (n: number): string => {
  if (!Number.isFinite(n) || n <= 0) return '$0'
  if (n < 0.0001) return `$${n.toFixed(6)}`
  if (n < 0.01) return `$${n.toFixed(5)}`
  if (n < 1) return `$${n.toFixed(4)}`
  return `$${n.toFixed(3)}`
}

/** Shorten a long id for narrow columns (middle ellipsis). */
export const shortenMiddle = (s: string, max: number): string => {
  if (s.length <= max) return s
  const inner = max - 1
  const left = Math.ceil(inner / 2)
  const right = Math.floor(inner / 2)
  return `${s.slice(0, left)}…${s.slice(s.length - right)}`
}

/** Render a JSON args object as a compact one-line string. */
export const fmtArgs = (args: Record<string, unknown>, maxLen = 60): string => {
  try {
    const s = JSON.stringify(args)
    return truncate(s, maxLen)
  } catch {
    return '{…}'
  }
}

/** Strip leading/trailing blank lines from a multi-line string. */
export const trimLines = (s: string): string => {
  return s.replace(/^\n+/, '').replace(/\n+$/, '')
}

/** Light markdown line transforms for non-fence prose (headings, lists, inline). */
const renderProseLines = (md: string, termWidth: number): string => {
  return md
    .split('\n')
    .map((line) => {
      const heading = /^(#{1,6})\s+(.+)$/.exec(line)
      if (heading) return `\x1b[1m${heading[2]}\x1b[0m`

      if (/^[-*_]{3,}$/.test(line.trim())) return '─'.repeat(Math.min(termWidth, 60))

      const bullet = /^(\s*)[-*+]\s+(.+)$/.exec(line)
      if (bullet) return `${bullet[1]}• ${bullet[2]}`

      const ordered = /^(\s*)\d+\.\s+(.+)$/.exec(line)
      if (ordered) return `${ordered[1]}  ${ordered[2]}`

      const quote = /^>\s+(.+)$/.exec(line)
      if (quote) return `\x1b[2m│ ${quote[1]}\x1b[0m`

      line = line.replace(/\*\*(.+?)\*\*|__(.+?)__/g, (_m, a, b) => `\x1b[1m${a ?? b}\x1b[0m`)
      line = line.replace(/\*(.+?)\*|_(.+?)_/g, (_m, a, b) => `\x1b[3m${a ?? b}\x1b[0m`)
      line = line.replace(/`([^`]+)`/g, (_m, code) => `\x1b[7m ${code} \x1b[0m`)

      return line
    })
    .join('\n')
}

const FENCE_RE = /```([\w+-]*)\n?([\s\S]*?)```/g

/**
 * Markdown-ish → terminal text. Fenced ``` blocks use cli-highlight (language-aware).
 * Inline prose uses the previous lightweight line rules.
 * Unmatched ``` fences fall through as normal prose (no fatal loop).
 */
export const renderMarkdown = (md: string, termWidth = 80): string => {
  let last = 0
  let out = ''
  let m: RegExpExecArray | null
  const s = md
  while ((m = FENCE_RE.exec(s)) !== null) {
    const before = s.slice(last, m.index)
    out += renderProseLines(before, termWidth)
    const lang = (m[1] || '').trim() || undefined
    const code = (m[2] ?? '').replace(/\n$/, '')
    try {
      out += highlight(code, { language: lang, ignoreIllegals: true })
      if (!out.endsWith('\n')) out += '\n'
    } catch {
      out += `\x1b[90m${code}\x1b[0m\n`
    }
    last = FENCE_RE.lastIndex
  }
  out += renderProseLines(s.slice(last), termWidth)
  return out
}

/** Produce a coloured status badge string (ANSI only; no React / TUI dependency). */
export const statusBadge = (status: string): string => {
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
