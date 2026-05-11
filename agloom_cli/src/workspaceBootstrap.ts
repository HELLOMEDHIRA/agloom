/**
 * Project workspace scaffold — **only invoked by the npm CLI** before spawning ``agloom-runtime``.
 * The Python runtime does not create ``agloom.yaml`` or ``.agloom/`` (transport-agnostic driver).
 */

import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { DEFAULT_AGLOOM_YAML } from './defaultAgloomTemplate.js'

export interface EnsureCliWorkspaceResult {
  /** True if at least one starter ``agloom.yaml`` was written. */
  wroteYaml: boolean
}

/** Create ``.agloom/{rules,skills,sessions}`` and starter YAML files when missing (sync). */
export function ensureAgloomCliWorkspace(cwd: string): EnsureCliWorkspaceResult {
  const dot = join(cwd, '.agloom')
  mkdirSync(join(dot, 'rules'), { recursive: true })
  mkdirSync(join(dot, 'skills'), { recursive: true })
  mkdirSync(join(dot, 'sessions'), { recursive: true })

  const rootYaml = join(cwd, 'agloom.yaml')
  const nestedYaml = join(dot, 'agloom.yaml')
  let wroteYaml = false

  if (!existsSync(rootYaml)) {
    writeFileSync(rootYaml, DEFAULT_AGLOOM_YAML, 'utf8')
    wroteYaml = true
  }
  if (!existsSync(nestedYaml)) {
    writeFileSync(nestedYaml, DEFAULT_AGLOOM_YAML, 'utf8')
    wroteYaml = true
  }

  return { wroteYaml }
}
