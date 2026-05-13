/** Project workspace scaffold — **only invoked by the npm CLI** before spawning ``agloom-runtime``.
 * The Python runtime does not create ``agloom.yaml`` or ``.agloom/`` (transport-agnostic driver).
 */

import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { DEFAULT_AGLOOM_YAML } from './defaultAgloomTemplate.js'
import { TEMPLATE_NODE_YAML, TEMPLATE_PYTHON_YAML } from './templateYaml.js'

export interface EnsureCliWorkspaceResult {
  /** True if starter ``./agloom.yaml`` was written (never duplicates ``.agloom/agloom.yaml``). */
  wroteYaml: boolean
}

export type InitTemplate = 'python' | 'node'

const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

const padToWidth = (s: string, width: number): string => {
  if (s.length >= width) return s.slice(0, width)
  return s + ' '.repeat(width - s.length)
}

/**
 * Run ``agsuperbrain init`` with a short explanation and a single-line stderr spinner
 * (child stdio is inherited so installer / graph output stays visible).
 */
const runAgsuperbrainInitWithLoader = (cwd: string): Promise<void> => {
  process.stderr.write(
    '[agloom] Initializing Super-Brain — running `agsuperbrain init`. First run can take 1–2 minutes (downloads / graph build).\n',
  )
  let frame = 0
  const spinnerLine = (): string => {
    const ch = SPINNER_FRAMES[frame % SPINNER_FRAMES.length]!
    frame++
    return `[agloom] ${ch} agsuperbrain init in progress…`
  }
  const tick = (): void => {
    process.stderr.write(`\r${padToWidth(spinnerLine(), 78)}`)
  }
  tick()
  const interval = setInterval(tick, 160)

  return new Promise((resolve) => {
    let settled = false
    const finish = (after?: () => void): void => {
      if (settled) return
      settled = true
      clearInterval(interval)
      process.stderr.write(`\r${padToWidth('', 78)}\r`)
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

/**
 * Create ``.agloom/{rules,skills,sessions}`` and, when needed, a **single** starter
 * ``agloom.yaml`` at the project root.
 *
 * We do **not** write ``.agloom/agloom.yaml`` here: walk-up discovery prefers the root file
 * first; a second copy was redundant and confusing. Legacy nested-only configs remain supported
 * via ``config.ts`` ``findWalkUpAgloomYaml``.
 */
export const ensureAgloomCliWorkspace = async(
  cwd: string,
  opts?: { template?: string },
): Promise<EnsureCliWorkspaceResult> => {
  const dot = join(cwd, '.agloom')
  mkdirSync(join(dot, 'rules'), { recursive: true })
  mkdirSync(join(dot, 'skills'), { recursive: true })
  mkdirSync(join(dot, 'sessions'), { recursive: true })

  const rootYaml = join(cwd, 'agloom.yaml')
  const nestedYaml = join(dot, 'agloom.yaml')
  let wroteYaml = false

  if (!existsSync(rootYaml) && !existsSync(nestedYaml)) {
    writeFileSync(rootYaml, yamlForTemplate(opts?.template), 'utf8')
    wroteYaml = true
  }

  // Bootstrap agsuperbrain knowledge graph if not already initialized
  const agsuperbrainDir = join(cwd, '.agsuperbrain')
  if (!existsSync(agsuperbrainDir)) {
    await runAgsuperbrainInitWithLoader(cwd)
  }

  return { wroteYaml }
}
