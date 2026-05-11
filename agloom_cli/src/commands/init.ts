/**
 * ``agloom init`` — write a starter ``agloom.yaml`` when missing.
 */

import { access, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { constants as fsConstants } from 'node:fs'

const TEMPLATE = `# Agloom — https://github.com/HELLOMEDHIRA/agloom
# CLI merges this file (walk-up discovery; override with \`agloom --config <path>\`).
# Keys are top-level — see agloom_cli/docs/config.md
model: groq:meta-llama/llama-3.3-70b-versatile
# provider: groq
`

export async function runInitCli(cwd: string): Promise<number> {
  const target = join(cwd, 'agloom.yaml')
  try {
    await access(target, fsConstants.F_OK)
    process.stderr.write(`[agloom] ${target} already exists — not overwriting.\n`)
    return 1
  } catch {
    // absent
  }
  await writeFile(target, TEMPLATE, 'utf8')
  process.stderr.write(`[agloom] wrote ${target}\n`)
  return 0
}
