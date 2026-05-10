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
 *   2. createAGPBridge() — spawns `agloom-runtime serve --transport=stdio` (stdio-only client)
 *   3. Render Ink <App> — subscribes to bridge events via useAGPStream
 *   4. On Ctrl+C or /exit the bridge is shut down gracefully before process exit
 */

import { render } from 'ink'
import React from 'react'
import { Command } from 'commander'
import { App } from './components/App.js'
import { createAGPBridge } from './runtime/bridge.js'

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
  .option('--no-cli-tools', 'do not pass --with-cli-tools to agloom-runtime', false)
  .option('--no-shell-tool', 'forward --cli-tools-no-shell (disable execute, bash, bash_background)', false)
  .option('--no-network-tools', 'forward --cli-tools-no-network', false)
  .option('--unrestricted', 'forward --cli-tools-no-sandbox (dangerous)', false)
  // Unknown flags are allowed so users can pass `-- --extra-arg` through to agloom-runtime.
  // Typos on *declared* options still fail validation; only unrecognized tokens slip through.
  .allowUnknownOption()

program.parse(process.argv)

const opts = program.opts<{
  thread?: string
  session?: string
  store: string
  storePath?: string
  diag: boolean
  noCliTools: boolean
  noShellTool: boolean
  noNetworkTools: boolean
  unrestricted: boolean
}>()

// ── Thread id ─────────────────────────────────────────────────────────────────

const thread = opts.thread ?? `t_${Date.now().toString(36)}`

// ── Runtime extra args ────────────────────────────────────────────────────────

const cwd = process.cwd()

const runtimeArgs: string[] = [
  '--store', opts.store,
  ...(opts.storePath ? ['--store-path', opts.storePath] : []),
  ...(opts.session ? ['--session', opts.session] : []),
  ...(opts.noCliTools
    ? []
    : ['--with-cli-tools', '--cli-tools-working-dir', cwd]),
  ...(opts.noShellTool ? ['--cli-tools-no-shell'] : []),
  ...(opts.noNetworkTools ? ['--cli-tools-no-network'] : []),
  ...(opts.unrestricted ? ['--cli-tools-no-sandbox'] : []),
]

const doubleDashIdx = process.argv.indexOf('--')
if (doubleDashIdx !== -1) {
  runtimeArgs.push(...process.argv.slice(doubleDashIdx + 1))
}

// ── Start the bridge ──────────────────────────────────────────────────────────

const bridge = createAGPBridge()
bridge.start(runtimeArgs, { transport: 'stdio' })

let exitCode = 0
bridge.once('exit', (info) => {
  if (info.code !== null && info.code !== 0) exitCode = info.code
  else if (info.signal != null && info.signal !== 'SIGTERM') exitCode = 1
})

bridge.once('error', (err: Error) => {
  process.stderr.write(`\n[agloom] bridge error: ${err.message}\n`)
  process.exit(1)
})

// ── Render the Ink app ────────────────────────────────────────────────────────

const { waitUntilExit } = render(
  React.createElement(App, {
    bridge,
    initialThread: thread,
    showDiag: opts.diag,
  }),
  { exitOnCtrlC: false }
)

try {
  await waitUntilExit()
} finally {
  if (bridge.status !== 'exited') bridge.kill()
  process.exit(exitCode)
}

