/** Canonical starter ``agloom.yaml`` body (written to ``.agloom/agloom.yaml`` by the CLI).
 * Runtime does not write project files — see ``workspaceBootstrap.ts``.
 *
 * ``ai.system_prompt`` is loaded from ``prompts/cli_workspace_prompt.txt`` (keep in sync with
 * ``agloom/prompts/cli_workspace_prompt.txt`` in the Python package).
 */

import { yamlIndentedPromptBlock } from './cliWorkspacePrompt.js'

export { CLI_WORKSPACE_SYSTEM_PROMPT } from './cliWorkspacePrompt.js'

export const DEFAULT_AGLOOM_YAML = `# Agloom — https://github.com/HELLOMEDHIRA/agloom
# CLI merges layers (see agloom_cli/docs/config.md): ~/.agloom → walk-up → --config → other CLI flags.
# multiline is YAML-only (no CLI flag); omit for default true (blank Enter sends). Routing pattern is chosen by the runtime, not configurable here.
#
# Defaults you usually edit (restart reloads YAML; no code path overwrites your file):
#   • model / ai.model          — provider:id (e.g. groq:meta-llama/llama-3.3-70b-versatile)
#   • ai.system_prompt          — default persona (or top-level system_prompt: | …)
#   • mcp.servers               — agsuperbrain → .agloom/mcp/agsuperbrain.yaml (stdio MCP; agsuperbrain CLI on PATH)
#   • .agloom/rules/            — drop *.md / *.mdc rule files; optional rules.dir if you relocate
#   • memory.* / skills.*       — tied to the store when present; tune limits below (no enable/disable toggles)

ai:
  name: agloom
  model: auto
  system_prompt: |
${yamlIndentedPromptBlock()}

mcp:
  servers:
    - agsuperbrain:mcp/agsuperbrain.yaml

tools:
  dir: ''
  disabled: []
  # When true (default), the npm CLI passes --with-cli-tools to the Python runtime.
  cli_enabled: true

memory:
  max_turns: 50
  auto_summarize: true

skills:
  max_skills: 30

rules:
  dir: ''
  refresh: false

execution:
  max_concurrent: 4
  max_retries: 2
  llm_timeout: 120.0
  classifier_timeout: 60.0

safety:
  require_approval: true
  auto_approve: ''
`
