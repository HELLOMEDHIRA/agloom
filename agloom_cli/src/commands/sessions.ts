/**
 * ``agloom sessions`` — list past sessions in a terminal UI and pick one to resume.
 */

import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import React from 'react'
import { render } from 'ink'
import { InkUiProvider } from '../components/InkUiProvider.js'
import { ThemeProvider } from '../themeContext.js'
import { SessionsPickerApp } from './SessionsPickerApp.js'
import { loadSessions, type SessionInfo } from './sessionsLoad.js'
import { resetTerminalForShell } from '../utils/terminalReset.js'

export type { SessionInfo } from './sessionsLoad.js'
export { loadSessions } from './sessionsLoad.js'

/** Resolve the CLI script path for spawning a nested ``agloom`` (no ``import.meta`` — Jest-safe). */
const resolveCliEntryForSpawn = (): string => {
  const a1 = process.argv[1]
  if (!a1) {
    throw new Error(
      'Cannot locate agloom CLI entry (process.argv[1] is empty). Reinstall agloom-cli or run via `node path/to/index.js`.',
    )
  }
  const p = resolve(a1)
  if (!existsSync(p)) {
    throw new Error(`Cannot locate agloom CLI entry at ${p}. Reinstall agloom-cli.`)
  }
  return p
}

const buildResumeArgv = (pick: SessionInfo): string[] => {
  const args: string[] = []
  if (pick.model && pick.model !== '—') {
    args.push('-m', pick.model)
  }
  args.push('--session', pick.id)
  if (pick.thread && pick.thread !== '—') {
    args.push('--thread', pick.thread)
  }
  return args
}

export const runSessionsCli = async (): Promise<number> => {
  const sessions = loadSessions()

  if (sessions.length === 0) {
    process.stdout.write('No past sessions found.\n')
    process.stdout.write('Start a session with: agloom -m <model>\n')
    return 0
  }

  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    process.stderr.write('[agloom] sessions: a TTY is required for the picker (use an interactive terminal).\n')
    sessions.slice(0, 20).forEach((s, idx) => {
      process.stdout.write(`${idx + 1}. ${s.id}  ${s.startedAt}\n`)
    })
    return 1
  }

  let chosen: SessionInfo | null = null
  const cliEntry = resolveCliEntryForSpawn()

  const ink = render(
    React.createElement(ThemeProvider, {
      value: 'dark',
      children: React.createElement(InkUiProvider, {
        children: React.createElement(SessionsPickerApp, {
          sessions,
          onChosen: (row) => {
            chosen = row
          },
        }),
      }),
    }),
    {
      exitOnCtrlC: true,
      alternateScreen: true,
      patchConsole: false,
    },
  )

  try {
    await ink.waitUntilExit()
  } finally {
    try {
      await ink.waitUntilRenderFlush()
    } catch {
      /* ignore */
    }
    resetTerminalForShell()
  }

  if (chosen === null) {
    process.stdout.write('\nNo session selected.\n')
    return 0
  }

  const pick: SessionInfo = chosen
  process.stderr.write(`\nResuming session ${pick.id} …\n\n`)

  const argv = buildResumeArgv(pick)
  const r = spawnSync(process.execPath, [cliEntry, ...argv], { stdio: 'inherit', shell: false })
  return r.status === null ? 1 : r.status
}
