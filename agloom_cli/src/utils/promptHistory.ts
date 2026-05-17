/** Optional transcript of submitted prompts (non-slash) for TUI recall — ~/.agloom/history.json */

import { randomBytes } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

const MAX_ENTRIES = 500

export const defaultHistoryPath = (): string => {
  return join(homedir(), '.agloom', 'history.json')
}

const writeJsonLineAtomic = (path: string, body: string): void => {
  const dir = dirname(path)
  mkdirSync(dir, { recursive: true })
  const tmp = join(dir, `.history.${process.pid}.${randomBytes(8).toString('hex')}.tmp`)
  writeFileSync(tmp, body, 'utf8')
  try {
    try {
      if (existsSync(path)) unlinkSync(path)
    } catch {
      /* ignore — concurrent writer */
    }
    renameSync(tmp, path)
  } catch (err) {
    try {
      if (existsSync(tmp)) unlinkSync(tmp)
    } catch {
      /* ignore */
    }
    throw err
  }
}

export const loadHistory = (path: string): string[] => {
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

export const appendHistory = (path: string, line: string): void => {
  const t = line.trim()
  if (!t || t.startsWith('/')) return
  try {
    const prev = loadHistory(path)
    const next = [...prev.filter((x) => x !== t), t].slice(-MAX_ENTRIES)
    writeJsonLineAtomic(path, `${JSON.stringify(next, null, 0)}\n`)
  } catch {
    /* ignore disk errors */
  }
}
