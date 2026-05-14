/** Project + user `agloom.yaml` layers, env fallbacks, and merge with Commander CLI state.
 * Precedence (low → high): defaults < user `~/.agloom/agloom.yaml` < walk-up `.agloom/agloom.yaml` then `./agloom.yaml` < `AGLOOM_*` env < explicit `--config` file < remaining CLI flags.
 * TUI **multiline** comes from merged YAML only (default on when omitted). Routing pattern is **not** user-configurable — the runtime classifier selects it.
 */

import { existsSync, readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, dirname, isAbsolute, join, resolve } from 'node:path'
import type { Command } from 'commander'
import YAML from 'yaml'
import { z } from 'zod'

/** CLI session memory is a simple slug (``sqlite`` / ``none`` / …); ignore structured maps. */
export const normalizeMemoryYamlInput = (raw: unknown): unknown => {
  return typeof raw === 'string' ? raw : undefined
}

type McpYamlEntry = string | { name: string; config: string }

export const _mcpEntryFromShorthandObject = (obj: Record<string, unknown>): McpYamlEntry | null => {
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
export const normalizeMcpYamlInput = (raw: unknown): unknown  =>{
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

/**
 * Rich-era / nested layouts use `ai.*`, object `memory`, `skills`, and `mcp.servers`.
 * Flatten into the top-level keys the Node CLI and Zod schema already understand.
 */
export const flattenRichAgloomYaml = (raw: unknown): unknown =>{
  if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) return raw
  const o = { ...(raw as Record<string, unknown>) }

  const ai = o.ai
  if (ai && typeof ai === 'object' && !Array.isArray(ai)) {
    const a = ai as Record<string, unknown>
    if (o.model === undefined || o.model === null) {
      if (a.model !== undefined && a.model !== null) o.model = a.model
    }
    if (o.provider === undefined || o.provider === null) {
      if (a.provider !== undefined && a.provider !== null) o.provider = a.provider
    }
    if (o.system_prompt === undefined || o.system_prompt === null) {
      if (a.system_prompt !== undefined && a.system_prompt !== null) o.system_prompt = a.system_prompt
    }
    if (o.system_prompt_file === undefined || o.system_prompt_file === null) {
      if (a.system_prompt_file !== undefined && a.system_prompt_file !== null) {
        o.system_prompt_file = a.system_prompt_file
      }
    }
  }

  const mem = o.memory
  if (mem && typeof mem === 'object' && !Array.isArray(mem)) {
    const m = mem as Record<string, unknown>
    const maxTurns = m.max_turns
    const enabled = m.enabled
    if (typeof maxTurns === 'number' && (o.session_max_turns === undefined || o.session_max_turns === null)) {
      o.session_max_turns = maxTurns
    }
    if (
      typeof m.auto_summarize === 'boolean' &&
      (o.auto_summarize === undefined || o.auto_summarize === null)
    ) {
      o.auto_summarize = m.auto_summarize
    }
    const sumModel = m.summarizer_model
    if (
      typeof sumModel === 'string' &&
      sumModel.trim().length > 0 &&
      (o.summarizer_model === undefined || o.summarizer_model === null)
    ) {
      o.summarizer_model = sumModel.trim()
    }
    if (typeof m.path === 'string' && m.path.trim().length > 0 && !o.memory_path) {
      o.memory_path = m.path
    }
    delete o.memory
    if (enabled === true) {
      o.memory = 'sqlite'
    } else if (enabled === false) {
      o.no_memory = true
    } else if (typeof m.backend === 'string' && m.backend.trim()) {
      o.memory = m.backend
    }
  }

  const skills = o.skills
  if (skills && typeof skills === 'object' && !Array.isArray(skills)) {
    const s = skills as Record<string, unknown>
    if (s.enabled === false) o.no_skills = true
    if (typeof s.dir === 'string' && s.dir.trim().length > 0 && !o.skills_dir) {
      o.skills_dir = s.dir
    }
  }

  const toolsRich = o.tools
  if (toolsRich && typeof toolsRich === 'object' && !Array.isArray(toolsRich)) {
    const tb = toolsRich as Record<string, unknown>
    if (tb.cli_enabled === false) {
      o.no_cli_tools = true
    }
  }

  const safety = o.safety
  if (safety && typeof safety === 'object' && !Array.isArray(safety)) {
    const sf = safety as Record<string, unknown>
    if (
      typeof sf.require_approval === 'boolean' &&
      (o.require_tool_approval === undefined || o.require_tool_approval === null)
    ) {
      o.require_tool_approval = sf.require_approval
    }
  }

  const mcpBlock = o.mcp
  if (mcpBlock && typeof mcpBlock === 'object' && !Array.isArray(mcpBlock)) {
    const mc = mcpBlock as Record<string, unknown>
    if (Array.isArray(mc.servers)) {
      o.mcp = mc.servers
    }
  }

  return o
}

const AgloomYamlSchema = z.preprocess(
  flattenRichAgloomYaml,
  z
    .object({
      model: z.string().optional(),
      provider: z.string().optional(),
      temperature: z.number().optional(),
      max_tokens: z.number().int().optional(),
      frequency_penalty: z.number().optional(),
      presence_penalty: z.number().optional(),
      /** TUI: multiline compose (blank Enter sends). Default true when omitted. */
      multiline: z.boolean().optional(),
      system_prompt: z.string().optional(),
      system_prompt_file: z.string().optional(),
      store: z.enum(['none', 'memory', 'sqlite']).optional(),
      store_path: z.string().optional(),
      memory: z.preprocess(normalizeMemoryYamlInput, z.string().optional()),
      memory_path: z.string().optional(),
      no_skills: z.boolean().optional(),
      skills_dir: z.string().optional(),
      summarizer_model: z.string().optional(),
      auto_summarize: z.boolean().optional(),
      session_max_turns: z.number().int().optional(),
      no_cli_tools: z.boolean().optional(),
      require_tool_approval: z.boolean().optional(),
      mcp: z.preprocess(
        normalizeMcpYamlInput,
        z.array(z.union([z.string(), z.object({ name: z.string(), config: z.string() })])).optional(),
      ),
    })
    .passthrough(),
)

export type AgloomYaml = z.infer<typeof AgloomYamlSchema>

/** Walk parents from `startDir` looking for ``.agloom/agloom.yaml`` first, then legacy root ``agloom.yaml``. */
export const findWalkUpAgloomYaml =(startDir: string): string | null => {
  let dir = resolve(startDir)
  while (true) {
    const nestedYaml = join(dir, '.agloom', 'agloom.yaml')
    if (existsSync(nestedYaml)) return nestedYaml
    const rootYaml = join(dir, 'agloom.yaml')
    if (existsSync(rootYaml)) return rootYaml
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  return null
}

/**
 * Project root for workspace files (``.agloom/``, ``.agsuperbrain/``) — matches Python
 * :func:`resolve_workspace_roots` when no store-path hints apply: walk-up from *cwd* for
 * ``.agloom/agloom.yaml`` first, then legacy root ``agloom.yaml``, else *cwd*.
 */
export const resolveAgloomProjectRoot = (cwd: string, explicitConfigPath?: string): string => {
  const p = explicitConfigPath?.trim()
  if (p) {
    const resolved = resolve(p)
    const parentDir = dirname(resolved)
    if (basename(parentDir) === '.agloom' && basename(resolved) === 'agloom.yaml') {
      return dirname(parentDir)
    }
    return parentDir
  }
  const y = findWalkUpAgloomYaml(cwd)
  if (!y) return resolve(cwd)
  const dir = dirname(y)
  return basename(dir) === '.agloom' ? dirname(dir) : dir
}

export const userGlobalAgloomPath = (): string => {
  return join(homedir(), '.agloom', 'agloom.yaml')
}

export const parseAgloomYamlFile = (path: string): AgloomYaml => {
  const raw = readFileSync(path, 'utf8')
  const doc = YAML.parse(raw)
  return AgloomYamlSchema.parse(doc ?? {})
}

/**
 * Merge YAML layers: user global → walk-up project → explicit override path (each wins over prior).
 *
 * **Shallow merge:** each layer replaces top-level keys from the previous layer. Nested blocks are
 * flattened by ``flattenRichAgloomYaml`` before Zod parse; unknown nested objects are still
 * subject to shallow replacement if two layers define the same top-level key. Extend merge
 * logic if we start preserving deep rich blocks without flattening.
 */
export const loadLayeredYaml = (cwd: string, explicitPath?: string): { merged: AgloomYaml; files: string[] } => {
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
export const mcpSpecsFromYaml = (
  mcp: AgloomYaml['mcp'],
  resolveRelativeTo: string,
): string[] => {
  if (!mcp || !Array.isArray(mcp)) return []
  const base = dirname(resolveRelativeTo)
  const out: string[] = []
  for (const entry of mcp) {
    if (typeof entry === 'string') {
      const colon = entry.indexOf(':')
      if (colon <= 0) {
        out.push(entry)
        continue
      }
      const name = entry.slice(0, colon).trim()
      const pathPart = entry.slice(colon + 1).trim()
      if (!pathPart || isAbsolute(pathPart)) {
        out.push(entry)
        continue
      }
      out.push(`${name}:${resolve(base, pathPart)}`)
      continue
    }
    const cfg = resolve(base, entry.config)
    out.push(`${entry.name}:${cfg}`)
  }
  return out
}

export type CliOptsLike = {
  model?: string
  provider?: string
  temperature?: number
  maxTokens?: number
  frequencyPenalty?: number
  presencePenalty?: number
  /** From merged ``agloom.yaml`` only; default true when unset. */
  multiline?: boolean
  systemPrompt?: string
  systemPromptFile?: string
  store: string
  storePath?: string
  memory?: string
  memoryPath?: string
  skillsDir?: string
  summarizerModel?: string
  noAutoSummarize: boolean
  sessionMaxTurns: number
  maxTurns?: number
  noCliTools?: boolean
  noRequireToolApproval?: boolean
  mcp: string[]
  attach?: string[]
  capture?: string
}

const envOverrides = (): Partial<CliOptsLike> => {
  const g = (k: string) => process.env[k]?.trim() || undefined
  const out: Partial<CliOptsLike> = {}
  const model = g('AGLOOM_MODEL')
  if (model) out.model = model
  const provider = g('AGLOOM_PROVIDER')
  if (provider) out.provider = provider
  const t = g('AGLOOM_TEMPERATURE')
  if (t) {
    const n = parseFloat(t)
    if (!Number.isNaN(n)) out.temperature = n
  }
  const fp = g('AGLOOM_FREQUENCY_PENALTY')
  if (fp) {
    const n = parseFloat(fp)
    if (!Number.isNaN(n)) out.frequencyPenalty = n
  }
  const pp = g('AGLOOM_PRESENCE_PENALTY')
  if (pp) {
    const n = parseFloat(pp)
    if (!Number.isNaN(n)) out.presencePenalty = n
  }
  return out
}

/**
 * Apply YAML + env to CLI opts without clobbering flags the user set on the command line.
 * Uses `commander` option value source when available (v9+).
 */
export const applyAgloomConfigLayers = (
  program: Command,
  base: CliOptsLike,
  cwd: string,
  configPath?: string,
): CliOptsLike =>{
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
  if (fromDefault('frequencyPenalty')) {
    if (env.frequencyPenalty !== undefined) next.frequencyPenalty = env.frequencyPenalty
    else if (y.frequency_penalty !== undefined) next.frequencyPenalty = y.frequency_penalty
  }
  if (fromDefault('presencePenalty')) {
    if (env.presencePenalty !== undefined) next.presencePenalty = env.presencePenalty
    else if (y.presence_penalty !== undefined) next.presencePenalty = y.presence_penalty
  }
  next.multiline = typeof y.multiline === 'boolean' ? y.multiline : true
  if (fromDefault('systemPrompt') && y.system_prompt) next.systemPrompt = y.system_prompt

  if (fromDefault('systemPromptFile') && y.system_prompt_file) {
    next.systemPromptFile = resolve(yamlBaseDir, y.system_prompt_file)
  }

  if (fromDefault('store') && y.store) next.store = y.store
  if (fromDefault('storePath') && y.store_path) next.storePath = resolve(yamlBaseDir, y.store_path)

  if (fromDefault('memory') && y.memory) next.memory = y.memory
  if (fromDefault('memoryPath') && y.memory_path) next.memoryPath = resolve(yamlBaseDir, y.memory_path)
  if (fromDefault('skillsDir') && y.skills_dir) next.skillsDir = resolve(yamlBaseDir, y.skills_dir)
  if (fromDefault('summarizerModel') && y.summarizer_model) next.summarizerModel = y.summarizer_model
  if (fromDefault('noAutoSummarize') && y.auto_summarize === false) next.noAutoSummarize = true
  if (fromDefault('sessionMaxTurns') && y.session_max_turns !== undefined)
    next.sessionMaxTurns = y.session_max_turns

  if (fromDefault('noCliTools') && y.no_cli_tools === true) next.noCliTools = true
  if (fromDefault('noRequireToolApproval') && y.require_tool_approval === false)
    next.noRequireToolApproval = true

  if (y.mcp && files.length > 0) {
    const extra = mcpSpecsFromYaml(y.mcp, files[files.length - 1]!)
    const nameFromSpec = (spec: string) => {
      const i = spec.indexOf(':')
      return i === -1 ? spec.trim() : spec.slice(0, i).trim()
    }
    const cliNames = new Set(next.mcp.map(nameFromSpec))
    const deduped = extra.filter((e) => !cliNames.has(nameFromSpec(e)))
    next.mcp = [...next.mcp, ...deduped]
  }

  return next
}

/** Resolved config for `--print-config` (includes merge provenance). */
export const buildResolvedConfigSnapshot =(
  program: Command,
  opts: CliOptsLike,
  cwd: string,
  configPath?: string,
): Record<string, unknown> => {
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
        'store',
        'memory',
        'sessionMaxTurns',
        'noCliTools',
        'noRequireToolApproval',
      ].map((k) => [
        k,
        (program as unknown as { getOptionValueSource?: (key: string) => string }).getOptionValueSource?.(k) ?? null,
      ]),
    ),
  }
}
