/**
 * Optional transcript of submitted prompts (non-slash) for TUI recall — ~/.agloom/history.json
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

const MAX_ENTRIES = 500

export function defaultHistoryPath(): string {
  return join(homedir(), '.agloom', 'history.json')
}

export function loadHistory(path: string): string[] {
  try {
    if (!existsSync(path)) return []
    const raw = readFileSync(path, 'utf8')
    const data = JSON.parse(raw) as unknown
    if (!Array.isArray(data)) return []
    return data.filter((x): x is string => typeof x === 'string').slice(-MAX_ENTRIES)
  } catch {
    return []
  }
}

export function appendHistory(path: string, line: string): void {
  const t = line.trim()
  if (!t || t.startsWith('/')) return
  try {
    const prev = loadHistory(path)
    const next = [...prev.filter((x) => x !== t), t].slice(-MAX_ENTRIES)
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, `${JSON.stringify(next, null, 0)}\n`, 'utf8')
  } catch {
    /* ignore disk errors */
  }
}
