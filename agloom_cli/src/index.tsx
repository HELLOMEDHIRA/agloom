#!/usr/bin/env node
/** Entry: `agloom-runtime serve` over stdio; direct one-shot or Ink TUI. Pass-through: `agloom -- …`. */

import { readFile } from 'node:fs/promises'
import { createWriteStream, type WriteStream } from 'node:fs'
import { basename, dirname, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { render } from 'ink'
import React from 'react'
import { Command } from 'commander'
import { App } from './components/App.js'
import { ThemeProvider, type AgloomTheme } from './themeContext.js'
import { createAGPBridge } from './runtime/bridge.js'
import { readStdinIfPiped } from './utils/readStdin.js'
import { runDirect } from './direct.js'
import { bannerEnvDisabled, formatBannerLine, readCliPackageVersion } from './banner.js'
import { applyAgloomConfigLayers, buildResolvedConfigSnapshot } from './config.js'
import { ensureAgloomCliWorkspace } from './workspaceBootstrap.js'
import type { AGPEvent, InvokeAttachment } from './types/agp.js'

type CliOpts = {
  thread?: string
  session?: string
  store: string
  storePath?: string
  diag: boolean
  noCliTools: boolean
  noRequireToolApproval: boolean
  noShellTool: boolean
  noNetworkTools: boolean
  unrestricted: boolean
  model?: string
  provider?: string
  apiKeyEnv?: string
  temperature?: number
  topP?: number
  topK?: number
  maxTokens?: number
  pattern?: string
  mcp: string[]
  systemPrompt?: string
  systemPromptFile?: string
  memory?: string
  memoryPath?: string
  skillsDir?: string
  summarizerModel?: string
  noAutoSummarize: boolean
  sessionMaxTurns: number
  /** From `--max-turns` (alias). */
  maxTurns?: number
  /** Direct / scripting */
  prompt?: string
  quiet: boolean
  json: boolean
  noStream: boolean
  noColor: boolean
  noBanner: boolean
  autoApprove: boolean
  autoReject: boolean
  hitlTty: boolean
  configPath?: string
  printConfig: boolean
  listProviders: boolean
  resolveModel?: string
  multiline: boolean
  historyFile?: string
  budgetTokens?: number
  budgetCostUsd?: number
  /** File paths forwarded as ``command.invoke`` attachments (base64 on the wire). */
  attach: string[]
  /** TUI: append each inbound AGP event as one NDJSON line. */
  capture?: string
  /** TUI: ``dark`` (default) or ``light`` terminal palette hints. */
  theme?: string
}

const doubleDash = process.argv.indexOf('--')
const argvMain = doubleDash === -1 ? process.argv : process.argv.slice(0, doubleDash)
const passthroughRuntime = doubleDash === -1 ? [] : process.argv.slice(doubleDash + 1)

const shouldPrintCombinedVersion = (argv: string[]): boolean => {
  const args = argv.slice(2)
  if (!args.some((a) => a === '--version' || a === '-V')) return false
  const firstSub = args.find((a) => !a.startsWith('-'))
  if (firstSub === 'init' || firstSub === 'eval' || firstSub === 'upgrade') return false
  return true
}

const readRuntimeSemverLine = (): string => {
  const run = process.env['AGLOOM_RUNTIME'] ?? 'agloom-runtime'
  const r = spawnSync(run, ['version'], { encoding: 'utf8', shell: false, maxBuffer: 256 })
  if (r.error || r.status !== 0) {
    return '(not available — install the `agloom` Python package so `agloom-runtime version` works)'
  }
  const line = (r.stdout ?? '').trim().split(/\r?\n/)[0] ?? ''
  return line || '(empty)'
}

const collectMcp = (v: string, prev: string[]): string[] => {
  return prev.concat([v])
}

const collectAttach = (v: string, prev: string[]): string[] => {
  return prev.concat([v])
}

/** Max bytes per ``--attach`` file (avoids loading huge blobs into memory). */
const MAX_ATTACH_BYTES = 32 * 1024 * 1024

const pathsToAttachments = async(paths: string[]): Promise<InvokeAttachment[]> => {
  const out: InvokeAttachment[] = []
  for (const p of paths) {
    const buf = await readFile(p)
    if (buf.length > MAX_ATTACH_BYTES) {
      throw new Error(
        `--attach ${p}: file is ${buf.length} bytes (limit ${MAX_ATTACH_BYTES} / 32 MiB per file)`,
      )
    }
    out.push({
      name: basename(p),
      mime_type: 'application/octet-stream',
      data_base64: buf.toString('base64'),
    })
  }
  return out
}

const exitWithRuntimeProviders = (subArgs: string[]): never => {
  const cmd = process.env['AGLOOM_RUNTIME'] ?? 'agloom-runtime'
  const r = spawnSync(cmd, ['providers', ...subArgs], { stdio: 'inherit', shell: false })
  const code = r.status === null ? 1 : r.status
  process.exit(code)
}

const cliVersion = readCliPackageVersion()

const program = new Command()
  .name('agloom')
  .description('agloom CLI — AGP terminal client (Ink + React) or one-shot direct mode')

program
  .command('upgrade')
  .description('Compare installed agloom-cli + agloom versions to npm / PyPI latest')
  .action(async () => {
    try {
      const { runUpgradeCli } = await import('./commands/upgrade.js')
      process.exit(await runUpgradeCli())
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      process.stderr.write(`[agloom] upgrade failed: ${msg}\n`)
      process.exit(1)
    }
  })

program
  .command('init')
  .description('Create .agloom/ directories and starter agloom.yaml when missing')
  .option('--config <path>', 'Use the directory containing this file as the project root')
  .option('--template <name>', 'starter agloom.yaml: python | node (optional)')
  .action(async (opts: { config?: string; template?: string }) => {
    try {
      const { runInitCli } = await import('./commands/init.js')
      const root = opts.config ? dirname(resolve(opts.config)) : process.cwd()
      process.exit(await runInitCli(root, { template: opts.template }))
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      process.stderr.write(`[agloom] init failed: ${msg}\n`)
      process.exit(1)
    }
  })

program
  .command('sessions')
  .description('List past sessions and pick one to resume')
  .action(async () => {
    try {
      const { runSessionsCli } = await import('./commands/sessions.js')
      process.exit(await runSessionsCli())
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      process.stderr.write(`[agloom] sessions failed: ${msg}\n`)
      process.exit(1)
    }
  })

program
  .command('clean')
  .description('Remove .agloom/, .agsuperbrain/, and clean .gitignore')
  .action(async () => {
    try {
      const { runCleanCli } = await import('./commands/clean.js')
      process.exit(await runCleanCli())
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      process.stderr.write(`[agloom] clean failed: ${msg}\n`)
      process.exit(1)
    }
  })

program
  .command('eval')
  .description('Run agloom-runtime eval (remaining argv forwarded after the optional file)')
  .allowUnknownOption(true)
  .action(() => {
    const run = process.env['AGLOOM_RUNTIME'] ?? 'agloom-runtime'
    const idx = argvMain.indexOf('eval')
    const tail = idx >= 0 ? argvMain.slice(idx + 1) : []
    const first = tail[0]
    const file = first && !first.startsWith('-') ? first : 'eval.yaml'
    const rest = first && !first.startsWith('-') ? tail.slice(1) : tail
    const r = spawnSync(run, ['eval', file, ...rest], { stdio: 'inherit', shell: false })
    process.exit(r.status === null ? 1 : r.status)
  })

program
  .argument('[prompt]', 'one-shot prompt (enables direct mode when stdin is TTY)')
  .option('-t, --thread <id>', 'LangGraph thread id')
  .option('-s, --session <id>', 'AGP session id')
  .option(
    '--store <type>',
    'AGP EventStore (replay/resume): none | memory | sqlite (default: sqlite → disk replay)',
    'sqlite',
  )
  .option(
    '--store-path <path>',
    'SQLite DB for AGP EventStore when --store=sqlite (default applied at runtime if omitted)',
  )
  .option('--diag', 'open diagnostic pane', false)
  .option('--no-cli-tools', 'omit --with-cli-tools (default: CLI tools on)', false)
  .option(
    '--no-require-tool-approval',
    'forward: allow CLI tools without per-tool HITL (matches agloom.yaml safety.require_approval: false)',
    false,
  )
  .option('--no-shell-tool', 'forward --cli-tools-no-shell', false)
  .option('--no-network-tools', 'forward --cli-tools-no-network', false)
  .option('--unrestricted', 'forward --cli-tools-no-sandbox', false)
  .option('-m, --model <id>', 'LLM model id (e.g. openai:gpt-4o)')
  .option('--provider <name>', 'force provider when ambiguous')
  .option('--api-key-env <var>', 'read API key from this env var (with --provider or prefixed model)')
  .option('-T, --temperature <n>', 'sampling temperature', parseFloat)
  .option('--top-p <n>', 'nucleus sampling top_p when supported', parseFloat)
  .option('--top-k <n>', 'top-k sampling when supported', (v) => parseInt(v, 10))
  .option('--max-tokens <n>', 'max output tokens', (v) => parseInt(v, 10))
  .option('--pattern <name>', 'routing bias: react, sequential, blackboard, …')
  .option('--mcp <spec>', 'MCP server name:path.yaml (repeatable)', collectMcp, [])
  .option('--attach <path>', 'direct mode: attach file as command.invoke payload (repeatable)', collectAttach, [])
  .option('--system-prompt <text>', 'system prompt')
  .option('--system-prompt-file <path>', 'system prompt from UTF-8 file')
  .option('--memory <type>', 'in-memory | none | sqlite')
  .option('--memory-path <path>', 'sqlite path for session memory')
  .option('--skills-dir <path>', 'skills disk mirror directory')
  .option('--summarizer-model <id>', 'summarizer model id')
  .option('--no-auto-summarize', 'disable auto summarization', false)
  .option('--session-max-turns <n>', 'SessionMemory max turns', (v) => parseInt(v, 10), 50)
  .option('--prompt <text>', 'direct prompt (alternative to positional)')
  .option('-q, --quiet', 'direct: stdout only (assistant text)', false)
  .option('--json', 'direct: print each AGP event as JSON line', false)
  .option('--no-stream', 'direct: buffer until message.assistant', false)
  .option('--no-color', 'direct: strip ANSI', false)
  .option('--no-banner', 'suppress ASCII banner', false)
  .option('--max-turns <n>', 'alias for --session-max-turns (agent session memory)', (v: string) =>
    parseInt(v, 10),
  )
  .option('--auto-approve', 'direct: auto-approve HITL gates (dangerous)', false)
  .option('--auto-reject', 'direct: auto-reject HITL gates', false)
  .option('--hitl-tty', 'direct: interactive HITL prompts on a TTY (direct mode)', false)
  .option('--config <path>', 'explicit agloom.yaml (overrides walk-up discovery)')
  .option('--print-config', 'print merged YAML/env/CLI resolution and exit', false)
  .option('--list-providers', 'print curated provider table from registry and exit', false)
  .option('--resolve-model <spec>', 'dry-run model resolution (Python registry); no LLM call')
  .option('--multiline', 'TUI: compose prompts over multiple lines (blank Enter sends)', false)
  .option('--theme <mode>', 'TUI: dark | light (subtle palette hints)', 'dark')
  .option('--history-file <path>', 'TUI: append-only prompt history JSON (default ~/.agloom/history.json)')
  .option(
    '--budget-tokens <n>',
    'forward to runtime: session cumulative token cap (input+output)',
    (v) => parseInt(v, 10),
  )
  .option('--budget-cost-usd <n>', 'forward to runtime: session cumulative USD cost cap', (v) => parseFloat(v))
  .option('--capture <path>', 'TUI: append each inbound AGP event as one NDJSON line', undefined)
  .allowUnknownOption(false)

if (shouldPrintCombinedVersion(argvMain)) {
  process.stdout.write(`agloom CLI ${cliVersion}\nagloom runtime ${readRuntimeSemverLine()}\n`)
  process.exit(0)
}

await program.parseAsync(argvMain, { from: 'node' })

const rawOpts = program.opts<CliOpts>()
const positionalPrompt = program.args[0] as string | undefined

const cwd = process.cwd()

if (rawOpts.listProviders) {
  exitWithRuntimeProviders(['list'])
}

if (rawOpts.resolveModel !== undefined && rawOpts.resolveModel !== '') {
  exitWithRuntimeProviders(['resolve', rawOpts.resolveModel])
}

if (rawOpts.printConfig) {
  process.stdout.write(
    `${JSON.stringify(buildResolvedConfigSnapshot(program, rawOpts, cwd, rawOpts.configPath), null, 2)}\n`,
  )
  process.exit(0)
}

const opts: CliOpts = {
  ...rawOpts,
  ...applyAgloomConfigLayers(program, rawOpts, cwd, rawOpts.configPath),
}

const themeRaw = (rawOpts.theme ?? 'dark').toLowerCase()
if (themeRaw !== 'dark' && themeRaw !== 'light') {
  process.stderr.write('[agloom] invalid --theme (use dark|light)\n')
  process.exit(2)
}
const themeUi: AgloomTheme = themeRaw === 'light' ? 'light' : 'dark'

const buildRuntimeArgs = (o: CliOpts): string[] => {
  const turns = o.maxTurns ?? o.sessionMaxTurns
  const parts: string[] = []
  parts.push('--store', o.store)
  if (o.store === 'sqlite') {
    parts.push('--store-path', o.storePath ?? '.agloom/agp_events.db')
  }
  if (o.session) parts.push('--session', o.session)
  if (o.model) parts.push('--model', o.model)
  if (o.provider) parts.push('--provider', o.provider)
  if (o.apiKeyEnv) parts.push('--api-key-env', o.apiKeyEnv)
  if (o.temperature !== undefined) parts.push('--temperature', String(o.temperature))
  if (o.topP !== undefined && !Number.isNaN(o.topP)) parts.push('--top-p', String(o.topP))
  if (o.topK !== undefined && !Number.isNaN(o.topK)) parts.push('--top-k', String(o.topK))
  if (o.maxTokens !== undefined) parts.push('--max-tokens', String(o.maxTokens))
  if (o.pattern) parts.push('--pattern', o.pattern)
  for (const m of o.mcp ?? []) {
    parts.push('--mcp', m)
  }
  if (o.systemPrompt) parts.push('--system-prompt', o.systemPrompt)
  if (o.systemPromptFile) parts.push('--system-prompt-file', o.systemPromptFile)
  if (o.memory) parts.push('--memory', o.memory)
  if (o.memoryPath) parts.push('--memory-path', o.memoryPath)
  if (o.skillsDir) parts.push('--skills-dir', o.skillsDir)
  if (o.summarizerModel) parts.push('--summarizer-model', o.summarizerModel)
  if (o.noAutoSummarize) parts.push('--no-auto-summarize')
  parts.push('--session-max-turns', String(turns))
  if (o.budgetTokens !== undefined && !Number.isNaN(o.budgetTokens) && o.budgetTokens > 0) {
    parts.push('--budget-tokens', String(Math.floor(o.budgetTokens)))
  }
  if (o.budgetCostUsd !== undefined && !Number.isNaN(o.budgetCostUsd) && o.budgetCostUsd > 0) {
    parts.push('--budget-cost-usd', String(o.budgetCostUsd))
  }
  if (!o.noCliTools) {
    parts.push('--with-cli-tools', '--cli-tools-working-dir', cwd)
  }
  if (o.noRequireToolApproval) {
    parts.push('--no-require-tool-approval')
  }
  if (o.noShellTool) parts.push('--cli-tools-no-shell')
  if (o.noNetworkTools) parts.push('--cli-tools-no-network')
  if (o.unrestricted) parts.push('--cli-tools-no-sandbox')
  parts.push(...passthroughRuntime)
  return parts
}

const stdinPrompt = await readStdinIfPiped()
const explicitPrompt = opts.prompt ?? positionalPrompt
const directPrompt = explicitPrompt ?? (stdinPrompt || undefined)

const directExec = Boolean(directPrompt && directPrompt.length > 0)

const thread = opts.thread ?? `t_${Date.now().toString(36)}`
const runtimeArgs = buildRuntimeArgs(opts)

if (directExec) {
  const bridge = createAGPBridge()
  const attachPaths = opts.attach ?? []
  const attachments = attachPaths.length > 0 ? await pathsToAttachments(attachPaths) : undefined
  await runDirect({
    bridge,
    prompt: directPrompt!,
    opts: {
      thread,
      quiet: opts.quiet,
      json: opts.json,
      noStream: opts.noStream,
      noColor: opts.noColor,
      noBanner: opts.noBanner || bannerEnvDisabled(),
      autoApprove: opts.autoApprove,
      autoReject: opts.autoReject,
      hitlTty: opts.hitlTty,
      attachments,
    },
    runtimeArgs,
  })
  process.exit(process.exitCode ?? 0)
}

try {
  ensureAgloomCliWorkspace(cwd)
} catch (err) {
  const msg = err instanceof Error ? err.message : String(err)
  process.stderr.write(`[agloom] workspace bootstrap failed: ${msg}\n`)
  process.exit(1)
}

const bridge = createAGPBridge()
let captureStream: WriteStream | undefined
let exitCode = 0
bridge.once('exit', (info) => {
  if (info.code !== null && info.code !== 0) exitCode = info.code
  else if (info.signal != null && info.signal !== 'SIGTERM') exitCode = 1
})

bridge.once('error', (err: Error) => {
  process.stderr.write(`\n[agloom] bridge error: ${err.message}\n`)
  process.exit(1)
})

if (opts.capture) {
  captureStream = createWriteStream(opts.capture, { flags: 'a' })
  bridge.on('event', (evt: AGPEvent) => {
    captureStream!.write(`${JSON.stringify(evt)}\n`)
  })
}

process.stderr.write('Starting agloom-runtime…\n')
bridge.start(runtimeArgs, { transport: 'stdio' })

if (!opts.noBanner && !bannerEnvDisabled()) {
  const ver = readCliPackageVersion()
  process.stderr.write(`${formatBannerLine({ version: ver })}\n`)
}

const { waitUntilExit } = render(
  React.createElement(ThemeProvider, {
    value: themeUi,
    children: React.createElement(App, {
      bridge,
      initialThread: thread,
      showDiag: opts.diag,
      multiline: rawOpts.multiline,
      historyFile: rawOpts.historyFile,
    }),
  }),
  { exitOnCtrlC: false },
)

try {
  await waitUntilExit()
} finally {
  captureStream?.end()
  if (bridge.status !== 'exited') bridge.kill()
  process.exit(exitCode)
}
