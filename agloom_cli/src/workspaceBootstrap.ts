/** Project workspace scaffold — **only invoked by the npm CLI** before spawning ``agloom-runtime``.
 * The Python runtime does not create ``agloom.yaml`` or ``.agloom/`` (transport-agnostic driver).
 */

import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import YAML from 'yaml'
import { resolveAgloomProjectRoot } from './config.js'
import { AGSUPERBRAIN_MCP_CONFIG_YAML } from './agsuperbrainMcpConfig.js'
import { DEFAULT_AGLOOM_YAML } from './defaultAgloomTemplate.js'
import { TEMPLATE_NODE_YAML, TEMPLATE_PYTHON_YAML } from './templateYaml.js'

export interface EnsureCliWorkspaceResult {
  /** True if ``.agloom/agloom.yaml`` was written this run (starter or migration from root). */
  wroteYaml: boolean
}

export type InitTemplate = 'python' | 'node'

const RULES_README = `Add rule files here (*.md, *.mdc). Set rules.dir in agloom.yaml to use another folder.
`

const HEARTBEAT_MS = 4000


/**
 * Run ``agsuperbrain init`` with a clear explanation, periodic stderr heartbeats (Windows-safe —
 * no ``\\r`` spinner), and inherited stdio so ``agsuperbrain`` logs stay visible.
 */
const runAgsuperbrainInitWithLoader = (cwd: string): Promise<void> => {
  process.stderr.write(
    '[agloom] Initializing Super-Brain — running `agsuperbrain init`. First run can take 1–2 minutes (downloads / graph build).\n',
  )
  const heartbeat = setInterval(() => {
    process.stderr.write('[agloom] … still running `agsuperbrain init` (this is normal on first run)\n')
  }, HEARTBEAT_MS)

  return new Promise((resolve) => {
    let settled = false
    const finish = (after?: () => void): void => {
      if (settled) return
      settled = true
      clearInterval(heartbeat)
      after?.()
      resolve()
    }
    const child = spawn('agsuperbrain', ['init'], {
      cwd,
      stdio: 'inherit',
      shell: false,
    })
    child.on('error', (err: NodeJS.ErrnoException) => {
      finish(() => {
        if (err.code === 'ENOENT') {
          process.stderr.write('[agloom] agsuperbrain not installed — MCP server unavailable\n')
        } else {
          process.stderr.write(`[agloom] could not run agsuperbrain: ${err.message}\n`)
        }
      })
    })
    child.on('close', (code) => {
      finish(() => {
        if (code === 0) {
          process.stderr.write('[agloom] Super-Brain workspace ready (./.agsuperbrain)\n')
        } else if (code !== null && code !== 0) {
          process.stderr.write(`[agloom] agsuperbrain init exited with code ${code}\n`)
        }
      })
    })
  })
}

const yamlForTemplate = (template?: string): string => {
  const t = (template || '').toLowerCase().trim()
  if (t === 'python') return TEMPLATE_PYTHON_YAML
  if (t === 'node') return TEMPLATE_NODE_YAML
  return DEFAULT_AGLOOM_YAML
}

const hasAgsuperbrainServerEntry = (servers: unknown[]): boolean =>
  servers.some((s) => {
    if (typeof s === 'string') return s.split(':')[0]?.trim().toLowerCase() === 'agsuperbrain'
    if (s && typeof s === 'object' && 'name' in (s as Record<string, unknown>)) {
      return String((s as { name: unknown }).name).trim().toLowerCase() === 'agsuperbrain'
    }
    return false
  })

/** Ensure nested project YAML lists the stdio Super-Brain MCP shim (``.agloom/mcp/agsuperbrain.yaml``). */
export const ensureAgsuperbrainMcpInNestedYaml = (nestedYamlPath: string): void => {
  if (!existsSync(nestedYamlPath)) return
  try {
    const raw = readFileSync(nestedYamlPath, 'utf8')
    const doc = YAML.parse(raw)
    if (doc == null || typeof doc !== 'object' || Array.isArray(doc)) return
    const rec = doc as Record<string, unknown>
    const mcpRaw = rec.mcp
    const mcp = mcpRaw && typeof mcpRaw === 'object' && !Array.isArray(mcpRaw) ? { ...(mcpRaw as object) } : {}
    const mcpRec = mcp as { servers?: unknown }
    const servers = Array.isArray(mcpRec.servers) ? [...mcpRec.servers] : []
    if (hasAgsuperbrainServerEntry(servers)) return
    servers.push('agsuperbrain:mcp/agsuperbrain.yaml')
    rec.mcp = { ...mcp, servers }
    writeFileSync(nestedYamlPath, YAML.stringify(rec, { lineWidth: 120 }), 'utf8')
    process.stderr.write(
      '[agloom] Added default `mcp.servers` entry `agsuperbrain:mcp/agsuperbrain.yaml` (Super-Brain MCP).\n',
    )
  } catch {
    process.stderr.write(
      `[agloom] could not patch MCP in ${nestedYamlPath}; add agsuperbrain under mcp.servers manually.\n`,
    )
  }
}

/**
 * Create ``.agloom/{rules,skills,sessions}`` and, when needed, ``.agloom/agloom.yaml`` (starter or copy
 * from legacy root ``agloom.yaml``). Walk-up discovery prefers nested YAML over root when both exist.
 */
export const ensureAgloomCliWorkspace = async(
  cwd: string,
  opts?: { template?: string; configPath?: string },
): Promise<EnsureCliWorkspaceResult> => {
  const projectRoot = resolveAgloomProjectRoot(cwd, opts?.configPath)
  const dot = join(projectRoot, '.agloom')
  mkdirSync(join(dot, 'rules'), { recursive: true })
  mkdirSync(join(dot, 'skills'), { recursive: true })
  mkdirSync(join(dot, 'sessions'), { recursive: true })

  const mcpDir = join(dot, 'mcp')
  mkdirSync(mcpDir, { recursive: true })
  const agsMcpYaml = join(mcpDir, 'agsuperbrain.yaml')
  if (!existsSync(agsMcpYaml)) {
    writeFileSync(agsMcpYaml, AGSUPERBRAIN_MCP_CONFIG_YAML, 'utf8')
  }
  const rulesReadme = join(dot, 'rules', 'README.txt')
  if (!existsSync(rulesReadme)) {
    writeFileSync(rulesReadme, RULES_README, 'utf8')
  }

  const rootYaml = join(projectRoot, 'agloom.yaml')
  const nestedYaml = join(dot, 'agloom.yaml')
  let wroteYaml = false

  if (!existsSync(nestedYaml)) {
    if (existsSync(rootYaml)) {
      writeFileSync(nestedYaml, readFileSync(rootYaml, 'utf8'), 'utf8')
      wroteYaml = true
      process.stderr.write(
        '[agloom] Migrated root `agloom.yaml` → `.agloom/agloom.yaml` (canonical). Remove the root file if you only want one copy — nested wins when both exist.\n',
      )
    } else {
      writeFileSync(nestedYaml, yamlForTemplate(opts?.template), 'utf8')
      wroteYaml = true
    }
  }

  if (existsSync(nestedYaml)) {
    ensureAgsuperbrainMcpInNestedYaml(nestedYaml)
  }

  // Bootstrap agsuperbrain knowledge graph if not already initialized (same root Python uses).
  const agsuperbrainDir = join(projectRoot, '.agsuperbrain')
  if (!existsSync(agsuperbrainDir)) {
    await runAgsuperbrainInitWithLoader(projectRoot)
  }

  return { wroteYaml }
}
