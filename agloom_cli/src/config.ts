/**
 * Project + user `agloom.yaml` layers, env fallbacks, and merge with Commander CLI state.
 *
 * Precedence (low → high): defaults < user `~/.agloom/agloom.yaml` < walk-up `./agloom.yaml` <
 * `AGLOOM_*` env < explicit `--config` file < CLI flags.
 */

import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import type { Command } from 'commander'
import YAML from 'yaml'
import { z } from 'zod'

/** CLI session memory is a simple slug (``sqlite`` / ``none`` / …); ignore structured maps. */
function normalizeMemoryYamlInput(raw: unknown): unknown {
  return typeof raw === 'string' ? raw : undefined
}

type McpYamlEntry = string | { name: string; config: string }

function _mcpEntryFromShorthandObject(obj: Record<string, unknown>): McpYamlEntry | null {
  const keys = Object.keys(obj)
  if (keys.length === 1) {
    const k = keys[0]!
    const v = obj[k]
    if (typeof v === 'string') return `${k}:${v}`
    return null
  }
  if (typeof obj.name === 'string' && typeof obj.config === 'string') {
    return { name: obj.name, config: obj.config }
  }
  return null
}

/**
 * Accept: map ``name: path`` / ``name: { config: path }``; array of strings, ``{ name, config }``,
 * or one-key objects from YAML list items (``- fs: ./x.yaml`` → ``{ fs: './x.yaml' }``).
 */
function normalizeMcpYamlInput(raw: unknown): unknown {
  if (raw == null) return undefined
  if (Array.isArray(raw)) {
    const out: McpYamlEntry[] = []
    for (const elem of raw) {
      if (typeof elem === 'string') {
        out.push(elem)
        continue
      }
      if (elem && typeof elem === 'object' && !Array.isArray(elem)) {
        const conv = _mcpEntryFromShorthandObject(elem as Record<string, unknown>)
        if (conv) out.push(conv)
      }
    }
    return out.length > 0 ? out : undefined
  }
  if (typeof raw !== 'object') return undefined
  const out: McpYamlEntry[] = []
  for (const [name, v] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof v === 'string') {
      out.push(`${name}:${v}`)
    } else if (v && typeof v === 'object' && typeof (v as { config?: unknown }).config === 'string') {
      out.push({ name, config: (v as { config: string }).config })
    }
  }
  return out.length > 0 ? out : undefined
}

const AgloomYamlSchema = z
  .object({
    model: z.string().optional(),
    provider: z.string().optional(),
    temperature: z.number().optional(),
    max_tokens: z.number().int().optional(),
    pattern: z.string().optional(),
    system_prompt: z.string().optional(),
    system_prompt_file: z.string().optional(),
    store: z.enum(['none', 'memory', 'sqlite']).optional(),
    store_path: z.string().optional(),
    memory: z.preprocess(normalizeMemoryYamlInput, z.string().optional()),
    memory_path: z.string().optional(),
    no_memory: z.boolean().optional(),
    no_skills: z.boolean().optional(),
    skills_dir: z.string().optional(),
    summarizer_model: z.string().optional(),
    auto_summarize: z.boolean().optional(),
    session_max_turns: z.number().int().optional(),
    mcp: z.preprocess(
      normalizeMcpYamlInput,
      z.array(z.union([z.string(), z.object({ name: z.string(), config: z.string() })])).optional(),
    ),
  })
  .passthrough()

export type AgloomYaml = z.infer<typeof AgloomYamlSchema>

/** Walk parents from `startDir` looking for `agloom.yaml` or legacy `.agloom/agloom.yaml`. */
export function findWalkUpAgloomYaml(startDir: string): string | null {
  let dir = resolve(startDir)
  while (true) {
    const rootYaml = join(dir, 'agloom.yaml')
    if (existsSync(rootYaml)) return rootYaml
    const nestedYaml = join(dir, '.agloom', 'agloom.yaml')
    if (existsSync(nestedYaml)) return nestedYaml
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return null
}

export function userGlobalAgloomPath(): string {
  return join(homedir(), '.agloom', 'agloom.yaml')
}

export function parseAgloomYamlFile(path: string): AgloomYaml {
  const raw = readFileSync(path, 'utf8')
  const doc = YAML.parse(raw)
  return AgloomYamlSchema.parse(doc ?? {})
}

/** Merge YAML layers: user global → walk-up project → explicit override path (each wins over prior). */
export function loadLayeredYaml(cwd: string, explicitPath?: string): { merged: AgloomYaml; files: string[] } {
  const files: string[] = []
  const layers: AgloomYaml[] = []

  const globalPath = userGlobalAgloomPath()
  if (existsSync(globalPath)) {
    layers.push(parseAgloomYamlFile(globalPath))
    files.push(globalPath)
  }

  const walk = findWalkUpAgloomYaml(cwd)
  if (walk) {
    layers.push(parseAgloomYamlFile(walk))
    files.push(walk)
  }

  if (explicitPath) {
    const p = resolve(explicitPath)
    if (!existsSync(p)) throw new Error(`--config file not found: ${p}`)
    layers.push(parseAgloomYamlFile(p))
    files.push(p)
  }

  const merged = layers.reduce<AgloomYaml>((acc, layer) => ({ ...acc, ...layer }), {})
  return { merged, files }
}

/** Expand MCP entries from YAML into `--mcp name:path` argv fragments (paths resolved vs YAML file dir). */
export function mcpSpecsFromYaml(
  mcp: AgloomYaml['mcp'],
  resolveRelativeTo: string,
): string[] {
  if (!mcp || !Array.isArray(mcp)) return []
  const base = dirname(resolveRelativeTo)
  const out: string[] = []
  for (const entry of mcp) {
    if (typeof entry === 'string') {
      out.push(entry)
    } else {
      const cfg = resolve(base, entry.config)
      out.push(`${entry.name}:${cfg}`)
    }
  }
  return out
}

export type CliOptsLike = {
  model?: string
  provider?: string
  temperature?: number
  maxTokens?: number
  pattern?: string
  systemPrompt?: string
  systemPromptFile?: string
  store: string
  storePath?: string
  noMemory: boolean
  memory?: string
  memoryPath?: string
  noSkills: boolean
  skillsDir?: string
  summarizerModel?: string
  noAutoSummarize: boolean
  sessionMaxTurns: number
  maxTurns?: number
  mcp: string[]
  attach?: string[]
}

function envOverrides(): Partial<CliOptsLike> {
  const g = (k: string) => process.env[k]?.trim() || undefined
  const out: Partial<CliOptsLike> = {}
  const model = g('AGLOOM_MODEL')
  if (model) out.model = model
  const provider = g('AGLOOM_PROVIDER')
  if (provider) out.provider = provider
  const pattern = g('AGLOOM_PATTERN')
  if (pattern) out.pattern = pattern
  const t = g('AGLOOM_TEMPERATURE')
  if (t) {
    const n = parseFloat(t)
    if (!Number.isNaN(n)) out.temperature = n
  }
  return out
}

/**
 * Apply YAML + env to CLI opts without clobbering flags the user set on the command line.
 * Uses `commander` option value source when available (v9+).
 */
export function applyAgloomConfigLayers(
  program: Command,
  base: CliOptsLike,
  cwd: string,
  configPath?: string,
): CliOptsLike {
  const { merged, files } = loadLayeredYaml(cwd, configPath)
  const yamlBaseDir = files.length > 0 ? dirname(files[files.length - 1]!) : cwd
  const y = merged
  const next: CliOptsLike = { ...base, mcp: [...(base.mcp ?? [])], attach: [...(base.attach ?? [])] }

  const src = (name: string) =>
    (program as unknown as { getOptionValueSource?: (k: string) => string | undefined }).getOptionValueSource?.(
      name,
    )

  const fromDefault = (name: string) => !src || src(name) === 'default' || src(name) === undefined

  const env = envOverrides()

  if (fromDefault('model')) {
    if (env.model) next.model = env.model
    else if (y.model) next.model = y.model
  }
  if (fromDefault('provider')) {
    if (env.provider) next.provider = env.provider
    else if (y.provider) next.provider = y.provider
  }
  if (fromDefault('temperature')) {
    if (env.temperature !== undefined) next.temperature = env.temperature
    else if (y.temperature !== undefined) next.temperature = y.temperature
  }
  if (fromDefault('maxTokens') && y.max_tokens !== undefined) next.maxTokens = y.max_tokens
  if (fromDefault('pattern')) {
    if (env.pattern) next.pattern = env.pattern
    else if (y.pattern) next.pattern = y.pattern
  }
  if (fromDefault('systemPrompt') && y.system_prompt) next.systemPrompt = y.system_prompt

  if (fromDefault('systemPromptFile') && y.system_prompt_file) {
    next.systemPromptFile = resolve(yamlBaseDir, y.system_prompt_file)
  }

  if (fromDefault('store') && y.store) next.store = y.store
  if (fromDefault('storePath') && y.store_path) next.storePath = resolve(yamlBaseDir, y.store_path)

  if (fromDefault('memory') && y.memory) next.memory = y.memory
  if (fromDefault('memoryPath') && y.memory_path) next.memoryPath = resolve(yamlBaseDir, y.memory_path)

  if (fromDefault('noMemory') && y.no_memory === true) next.noMemory = true
  if (fromDefault('noSkills') && y.no_skills === true) next.noSkills = true
  if (fromDefault('skillsDir') && y.skills_dir) next.skillsDir = resolve(yamlBaseDir, y.skills_dir)

  if (fromDefault('summarizerModel') && y.summarizer_model) next.summarizerModel = y.summarizer_model
  if (fromDefault('noAutoSummarize') && y.auto_summarize === false) next.noAutoSummarize = true
  if (fromDefault('sessionMaxTurns') && y.session_max_turns !== undefined)
    next.sessionMaxTurns = y.session_max_turns

  if (y.mcp && files.length > 0) {
    const extra = mcpSpecsFromYaml(y.mcp, files[files.length - 1]!)
    next.mcp = [...next.mcp, ...extra]
  }

  return next
}

/** Resolved config for `--print-config` (includes merge provenance). */
export function buildResolvedConfigSnapshot(
  program: Command,
  opts: CliOptsLike,
  cwd: string,
  configPath?: string,
): Record<string, unknown> {
  const { merged, files } = loadLayeredYaml(cwd, configPath)
  const applied = applyAgloomConfigLayers(program, opts, cwd, configPath)
  return {
    yaml_files: files,
    yaml_merged: merged,
    env: envOverrides(),
    cli_effective: applied,
    option_sources: Object.fromEntries(
      [
        'model',
        'provider',
        'temperature',
        'pattern',
        'store',
        'memory',
        'sessionMaxTurns',
      ].map((k) => [
        k,
        (program as unknown as { getOptionValueSource?: (key: string) => string }).getOptionValueSource?.(k) ?? null,
      ]),
    ),
  }
}
