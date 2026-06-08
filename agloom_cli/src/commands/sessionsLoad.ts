/**
 * Scan ``.agloom/sessions`` (cwd + home) for session marker JSON files — no Ink / React.
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { resolve } from 'node:path'

export interface SessionInfo {
  id: string
  startedAt: string
  model: string
  provider: string
  thread: string
  turns: number
  transport: string
}

const findSessionsDirs = (): string[] => {
  const candidates: string[] = []
  const cwd = process.cwd()
  const dot = resolve(cwd, '.agloom', 'sessions')
  if (existsSync(dot)) candidates.push(dot)
  const home = resolve(homedir(), '.agloom', 'sessions')
  if (existsSync(home) && home !== dot) candidates.push(home)
  return candidates
}

const readEffective = (d: Record<string, unknown>): Record<string, unknown> => {
  const e = d.effective_config
  return e && typeof e === 'object' && !Array.isArray(e) ? (e as Record<string, unknown>) : {}
}

export const loadSessions = (): SessionInfo[] => {
  const sessions: SessionInfo[] = []
  for (const dir of findSessionsDirs()) {
    let entries: string[]
    try {
      entries = readdirSync(dir)
    } catch {
      continue
    }
    for (const f of entries) {
      if (!f.endsWith('.json')) continue
      try {
        const raw = readFileSync(resolve(dir, f), 'utf8')
        const d = JSON.parse(raw) as Record<string, unknown>
        if (!d.session_id) continue
        const eff = readEffective(d)
        const model = String(d.model ?? eff.model ?? '—')
        const provider = String(
          d.provider ?? eff.provider_resolved ?? eff.provider ?? '—',
        )
        const turns =
          typeof d.turns === 'number'
            ? d.turns
            : typeof eff.turns === 'number'
              ? (eff.turns as number)
              : 0
        sessions.push({
          id: String(d.session_id),
          startedAt: String(d.started_at ?? ''),
          model,
          provider,
          thread: String(d.initial_thread ?? '—'),
          turns,
          transport: String(d.transport ?? 'stdio'),
        })
      } catch {
        // skip unparseable files
      }
    }
  }
  sessions.sort((a, b) => b.startedAt.localeCompare(a.startedAt))
  return sessions
}
