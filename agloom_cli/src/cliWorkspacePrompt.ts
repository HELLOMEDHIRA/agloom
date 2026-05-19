/** Canonical CLI workspace system prompt — must match ``agloom/prompts/cli_workspace_prompt.txt``. */

import { existsSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'

const PROMPT_REL = join('prompts', 'cli_workspace_prompt.txt')

function resolvePromptPath(): string {
  const tried: string[] = []
  const hit = (p: string): string | null => {
    tried.push(p)
    return existsSync(p) ? p : null
  }

  const entry = process.argv[1]
  if (entry) {
    try {
      const req = createRequire(entry)
      const pkgJson = req.resolve('agloom-cli/package.json')
      const fromPkg = join(dirname(pkgJson), 'prompts', 'cli_workspace_prompt.txt')
      const found = hit(fromPkg)
      if (found) return found
    } catch {
      const nearBin = join(dirname(entry), '..', PROMPT_REL)
      const found = hit(nearBin)
      if (found) return found
    }
  }

  for (const base of [
    join(process.cwd(), 'node_modules', 'agloom-cli'),
    join(process.cwd(), 'agloom_cli'),
    process.cwd(),
  ]) {
    const found = hit(join(base, PROMPT_REL))
    if (found) return found
  }

  throw new Error(`cli_workspace_prompt.txt not found (tried: ${tried.join('; ')})`)
}

/** Resolved at runtime from the shipped ``prompts/`` directory next to the CLI package. */
export const CLI_WORKSPACE_SYSTEM_PROMPT = readFileSync(resolvePromptPath(), 'utf8').trimEnd() + '\n'

const LEGACY_MARKERS = [
  'built with agloom',
  '## your capabilities',
  'autonomous ai programming assistant built with agloom',
  '## guidelines',
  '## code style',
] as const

const CANONICAL_MARKER = 'terminal workspace (agloom cli)'

export const isCanonicalCliSystemPrompt = (text: string): boolean =>
  text.trim() === CLI_WORKSPACE_SYSTEM_PROMPT.trim()

export const isLegacyCliSystemPrompt = (text: string): boolean => {
  const t = text.trim().toLowerCase()
  if (t.includes(CANONICAL_MARKER)) return false
  return LEGACY_MARKERS.some((m) => t.includes(m))
}

export const yamlIndentedPromptBlock = (text: string = CLI_WORKSPACE_SYSTEM_PROMPT): string =>
  text
    .trimEnd()
    .split('\n')
    .map((line) => `    ${line}`)
    .join('\n')
