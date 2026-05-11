/**
 * ``agloom init`` — scaffold ``.agloom/{rules,skills,sessions}`` and starter YAML (same as first CLI run).
 */

import { join } from 'node:path'
import { ensureAgloomCliWorkspace } from '../workspaceBootstrap.js'

export async function runInitCli(cwd: string): Promise<number> {
  const { wroteYaml } = ensureAgloomCliWorkspace(cwd)
  process.stderr.write(`[agloom] ensured .agloom/rules, .agloom/skills, .agloom/sessions\n`)
  const target = join(cwd, 'agloom.yaml')
  const dotYaml = join(cwd, '.agloom', 'agloom.yaml')
  if (wroteYaml) {
    process.stderr.write(`[agloom] wrote starter YAML (if missing): ${target} and/or ${dotYaml}\n`)
  } else {
    process.stderr.write(`[agloom] ${target} and ${dotYaml} already exist — not overwriting.\n`)
  }
  return 0
}
