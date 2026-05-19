import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import YAML from 'yaml'
import {
  CLI_WORKSPACE_SYSTEM_PROMPT,
  isCanonicalCliSystemPrompt,
  isLegacyCliSystemPrompt,
} from '../cliWorkspacePrompt.js'
import { DEFAULT_AGLOOM_YAML } from '../defaultAgloomTemplate.js'
import { migrateLegacySystemPromptInYaml } from '../yamlSystemPromptMigrate.js'

const repoRoot = join(process.cwd(), '..')
const pyPromptPath = join(repoRoot, 'agloom', 'prompts', 'cli_workspace_prompt.txt')

describe('cli_workspace_prompt.txt sync', () => {
  it('matches Python package prompt file', () => {
    const py = readFileSync(pyPromptPath, 'utf8').trimEnd() + '\n'
    expect(CLI_WORKSPACE_SYSTEM_PROMPT).toBe(py)
  })

  it('DEFAULT_AGLOOM_YAML embeds canonical system_prompt', () => {
    const doc = YAML.parse(DEFAULT_AGLOOM_YAML) as { ai?: { system_prompt?: string } }
    const sp = doc.ai?.system_prompt?.trim() ?? ''
    expect(isCanonicalCliSystemPrompt(sp)).toBe(true)
  })

  it('detects legacy starter prompt', () => {
    const legacy = 'You are an autonomous AI programming assistant built with agloom.\n## Your Capabilities'
    expect(isLegacyCliSystemPrompt(legacy)).toBe(true)
    expect(isLegacyCliSystemPrompt(CLI_WORKSPACE_SYSTEM_PROMPT)).toBe(false)
  })
})

describe('migrateLegacySystemPromptInYaml', () => {
  it('does not inject prompt when system_prompt is missing', () => {
    const dir = join(repoRoot, 'agloom_cli', 'src', '__tests__', '_tmp_yaml_empty')
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
    const p = join(dir, 'agloom.yaml')
    writeFileSync(p, 'ai:\n  model: auto\n', 'utf8')
    expect(migrateLegacySystemPromptInYaml(p)).toBe(false)
    expect(readFileSync(p, 'utf8')).not.toContain('terminal workspace')
    rmSync(dir, { recursive: true, force: true })
  })

  it('rewrites legacy ai.system_prompt', () => {
    const dir = join(repoRoot, 'agloom_cli', 'src', '__tests__', '_tmp_yaml_migrate')
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
    const p = join(dir, 'agloom.yaml')
    writeFileSync(
      p,
      'ai:\n  system_prompt: |\n    built with agloom\n    ## Your Capabilities\n',
      'utf8',
    )
    expect(migrateLegacySystemPromptInYaml(p)).toBe(true)
    const doc = YAML.parse(readFileSync(p, 'utf8')) as { ai?: { system_prompt?: string } }
    expect(isCanonicalCliSystemPrompt(doc.ai?.system_prompt ?? '')).toBe(true)
    rmSync(dir, { recursive: true, force: true })
  })
})
