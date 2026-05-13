/**
 * ``agloom sessions`` — list past sessions and pick one to resume.
 */

import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

interface SessionInfo {
  id: string
  startedAt: string
  model: string
  provider: string
  thread: string
  turns: number
  transport: string
}

function findSessionsDirs(): string[] {
  const candidates: string[] = []
  const cwd = process.cwd()
  const dot = join(cwd, '.agloom', 'sessions')
  if (existsSync(dot)) candidates.push(dot)
  const home = join(homedir(), '.agloom', 'sessions')
  if (existsSync(home) && home !== dot) candidates.push(home)
  return candidates
}

function loadSessions(): SessionInfo[] {
  const sessions: SessionInfo[] = []
  for (const dir of findSessionsDirs()) {
    let entries: string[]
    try { entries = readdirSync(dir) } catch { continue }
    for (const f of entries) {
      if (!f.endsWith('.json')) continue
      try {
        const raw = readFileSync(join(dir, f), 'utf8')
        const d = JSON.parse(raw) as Record<string, unknown>
        if (!d.session_id) continue
        sessions.push({
          id: String(d.session_id),
          startedAt: String(d.started_at ?? ''),
          model: String(d.model ?? '—'),
          provider: String(d.provider ?? '—'),
          thread: String(d.initial_thread ?? '—'),
          turns: typeof d.turns === 'number' ? d.turns : 0,
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

function fmtDate(iso: string): string {
  if (!iso || iso === '—') return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso.slice(0, 16)
  }
}

function trunc(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1) + '…'
}

export async function runSessionsCli(): Promise<number> {
  const sessions = loadSessions()

  if (sessions.length === 0) {
    process.stdout.write('No past sessions found.\n')
    process.stdout.write('Start a session with: agloom -m <model>\n')
    return 0
  }

  // ── Table header ──────────────────────────────────────────────────────
  const rows: string[] = []
  const hdr = `  ${'#'.padEnd(3)} ${'Session ID'.padEnd(24)} ${'Started'.padEnd(16)} ${'Model'.padEnd(22)} ${'Turns'}`
  rows.push(hdr)
  rows.push('  ' + '─'.repeat(hdr.length - 2))

  for (let i = 0; i < sessions.length; i++) {
    const s = sessions[i]!
    const idx = String(i + 1).padEnd(3)
    const sid = trunc(s.id, 22).padEnd(24)
    const date = fmtDate(s.startedAt).padEnd(16)
    const mdl = trunc(s.model, 20).padEnd(22)
    const turns = String(s.turns).padStart(5)
    rows.push(`  ${idx} ${sid} ${date} ${mdl} ${turns}`)
  }

  process.stdout.write('\n')
  process.stdout.write('  ╔════════════════════════════════════════════════════════════════════════════╗\n')
  process.stdout.write('  ║                          Past Sessions                                  ║\n')
  process.stdout.write('  ╚════════════════════════════════════════════════════════════════════════════╝\n')
  process.stdout.write('\n')
  process.stdout.write(rows.join('\n') + '\n')
  process.stdout.write('\n')

  // ── Prompt user to pick one ───────────────────────────────────────────
  const rl = (await import('node:readline/promises')).createInterface({
    input: process.stdin,
    output: process.stdout,
  })

  try {
    const ans = await rl.question('  Enter session number to resume (or blank to exit): ')
    const n = parseInt(ans.trim(), 10)
    if (isNaN(n) || n < 1 || n > sessions.length) {
      process.stdout.write('  No session selected.\n')
      return 0
    }

    const pick = sessions[n - 1]!
    process.stdout.write(`\n  Resuming session ${pick.id} (model: ${pick.model})...\n\n`)

    // Launch agloom CLI with this session
    const { spawnSync } = await import('node:child_process')
    const node = process.execPath
    const cliEntry = new URL('../index.js', import.meta.url).pathname
    const args = [cliEntry, ...(pick.model !== '—' ? ['-m', pick.model] : []), '--session', pick.id]
    if (pick.thread !== '—') args.push('--thread', pick.thread)
    process.stdout.write(`  Starting: agloom ${args.slice(1).join(' ')}\n\n`)
    const r = spawnSync(node, args, { stdio: 'inherit', shell: false })
    return r.status === null ? 1 : r.status
  } finally {
    rl.close()
  }
}
