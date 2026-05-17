/** Optional ``agloom init --template`` starter bodies (written to ``.agloom/agloom.yaml``). */

export const TEMPLATE_PYTHON_YAML = `# Agloom — Python project (from \`agloom init --template python\`)
ai:
  name: agloom
  model: auto
  system_prompt: |
    You are a senior Python engineer. Prefer type hints, pytest, and ruff-compatible style.
    Use tools to read and edit files; run tests after substantive changes.

mcp:
  servers:
    - agsuperbrain:mcp/agsuperbrain.yaml

tools:
  dir: ''
  disabled: []
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

export const TEMPLATE_NODE_YAML = `# Agloom — Node/TypeScript project (from \`agloom init --template node\`)
ai:
  name: agloom
  model: auto
  system_prompt: |
    You are a senior TypeScript engineer. Prefer strict typing, eslint-friendly code, and npm scripts.
    Use tools to read and edit files; run \`npm test\` or \`pnpm test\` after substantive changes.

mcp:
  servers:
    - agsuperbrain:mcp/agsuperbrain.yaml

tools:
  dir: ''
  disabled: []
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
