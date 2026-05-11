/**
 * ``agloom init`` — scaffold ``.agloom/{rules,skills,sessions}`` and starter YAML (Rich-era layout).
 */

import { access, mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { constants as fsConstants } from 'node:fs'

const TEMPLATE = `# Agloom — https://github.com/HELLOMEDHIRA/agloom
# CLI merges this file (walk-up discovery; override with \`agloom --config <path>\`).
# Keys are top-level — see agloom_cli/docs/config.md
model: groq:meta-llama/llama-3.3-70b-versatile
# provider: groq
`

export async function runInitCli(cwd: string): Promise<number> {
  const dot = join(cwd, '.agloom')
  await mkdir(join(dot, 'rules'), { recursive: true })
  await mkdir(join(dot, 'skills'), { recursive: true })
  await mkdir(join(dot, 'sessions'), { recursive: true })
  process.stderr.write(`[agloom] ensured .agloom/rules, .agloom/skills, .agloom/sessions\n`)

  const target = join(cwd, 'agloom.yaml')
  const dotYaml = join(dot, 'agloom.yaml')
  let wrote = false

  try {
    await access(target, fsConstants.F_OK)
  } catch {
    await writeFile(target, TEMPLATE, 'utf8')
    process.stderr.write(`[agloom] wrote ${target}\n`)
    wrote = true
  }

  try {
    await access(dotYaml, fsConstants.F_OK)
  } catch {
    await writeFile(dotYaml, TEMPLATE, 'utf8')
    process.stderr.write(`[agloom] wrote ${dotYaml}\n`)
    wrote = true
  }

  if (!wrote) {
    process.stderr.write(`[agloom] ${target} and ${dotYaml} already exist — not overwriting.\n`)
  }
  return 0
}
