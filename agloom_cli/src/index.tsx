#!/usr/bin/env node
/**
 * agloom CLI entrypoint (npm package `agloom-cli`).
 *
 * Spawns `agloom-runtime` as a child process, then renders the terminal UI (Ink + React)
 * on top of the streaming AGP event bus.
 *
 * Usage:
 *   agloom [options] [-- extra-runtime-args...]
 *
 * Bootstrap flow:
 *   1. Parse CLI args (Commander)
 *   2. Create AGPBridge — spawns `agloom-runtime serve --transport=stdio`
 *   3. Render Ink <App> — subscribes to bridge events via useAGPStream
 *   4. On Ctrl+C or /exit the bridge is shut down gracefully before process exit
 */

import { render } from 'ink'
import React from 'react'
import { Command } from 'commander'
import { App } from './components/App.js'
import { AGPBridge } from './runtime/bridge.js'

// ── CLI argument parsing ───────────────────────────────────────────────────────

const program = new Command()
  .name('agloom')
  .description('agloom CLI — AGP terminal client (Ink + React)')
  .version('0.1.0')
  .option('-t, --thread <id>', 'LangGraph thread id to resume or create')
  .option('-s, --session <id>', 'AGP session id to attach to')
  .option('--store <type>', 'EventStore backend: none | memory | sqlite', 'memory')
  .option('--store-path <path>', 'SQLite store path (when --store=sqlite)')
  .option('--diag', 'open the diagnostic log pane on start', false)
  .option('--transport <type>', 'Runtime transport override (default: stdio)', 'stdio')
  .allowUnknownOption()

program.parse(process.argv)

const opts = program.opts<{
  thread?: string
  session?: string
  store: string
  storePath?: string
  diag: boolean
  transport: string
}>()

// ── Thread id ─────────────────────────────────────────────────────────────────

const thread = opts.thread ?? `t_${Date.now().toString(36)}`

// ── Runtime extra args ────────────────────────────────────────────────────────

const runtimeArgs: string[] = [
  '--store', opts.store,
  ...(opts.storePath ? ['--store-path', opts.storePath] : []),
]

const doubleDashIdx = process.argv.indexOf('--')
if (doubleDashIdx !== -1) {
  runtimeArgs.push(...process.argv.slice(doubleDashIdx + 1))
}

// ── Start the bridge ──────────────────────────────────────────────────────────

const bridge = new AGPBridge()
bridge.start(runtimeArgs)

bridge.once('error', (err: Error) => {
  process.stderr.write(`\n[agloom] bridge error: ${err.message}\n`)
  process.exit(1)
})

// ── Render the Ink app ────────────────────────────────────────────────────────

const { waitUntilExit } = render(
  React.createElement(App, {
    bridge,
    initialThread: thread,
    session: opts.session,
    showDiag: opts.diag,
  }),
  { exitOnCtrlC: false }
)

try {
  await waitUntilExit()
} finally {
  if (bridge.status !== 'exited') bridge.kill()
  process.exit(0)
}

