/** ``agloom init`` — scaffold ``.agloom/{rules,skills,sessions}`` and starter YAML (same as first CLI run). */

import { join } from 'node:path'
import { ensureAgloomCliWorkspace } from '../workspaceBootstrap.js'

export const runInitCli = async(cwd: string, opts?: { template?: string }): Promise<number> => {
  const { wroteYaml } = await ensureAgloomCliWorkspace(cwd, { template: opts?.template })
  process.stderr.write(`[agloom] ensured .agloom/rules, .agloom/skills, .agloom/sessions\n`)
  const target = join(cwd, '.agloom', 'agloom.yaml')
  const legacyRoot = join(cwd, 'agloom.yaml')
  if (wroteYaml) {
    const tag = opts?.template ? ` (template=${opts.template})` : ''
    process.stderr.write(`[agloom] wrote starter project YAML: ${target}${tag}\n`)
  } else {
    process.stderr.write(
      `[agloom] project YAML already present (${target} or legacy ${legacyRoot}) — not overwriting.\n`,
    )
  }
  return 0
}
