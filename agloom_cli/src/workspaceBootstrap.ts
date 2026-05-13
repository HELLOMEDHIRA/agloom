/** Project workspace scaffold — **only invoked by the npm CLI** before spawning ``agloom-runtime``.
 * The Python runtime does not create ``agloom.yaml`` or ``.agloom/`` (transport-agnostic driver).
 */

import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { DEFAULT_AGLOOM_YAML } from './defaultAgloomTemplate.js'
import { TEMPLATE_NODE_YAML, TEMPLATE_PYTHON_YAML } from './templateYaml.js'

export interface EnsureCliWorkspaceResult {
  /** True if starter ``./agloom.yaml`` was written (never duplicates ``.agloom/agloom.yaml``). */
  wroteYaml: boolean
}

export type InitTemplate = 'python' | 'node'

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
export const ensureAgloomCliWorkspace = (cwd: string, opts?: { template?: string }): EnsureCliWorkspaceResult => {
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
    const r = spawnSync('agsuperbrain', ['init'], {
      stdio: 'inherit',
      shell: false,
    })
    if (r.error && (r.error as NodeJS.ErrnoException).code === 'ENOENT') {
      process.stderr.write('[agloom] agsuperbrain not installed — MCP server unavailable\n')
    } else if (r.status !== 0) {
      process.stderr.write(`[agloom] agsuperbrain init exited with code ${r.status ?? 'null'}\n`)
    }
  }

  return { wroteYaml }
}
