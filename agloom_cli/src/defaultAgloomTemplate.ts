/** Canonical starter ``agloom.yaml`` body (written to ``.agloom/agloom.yaml`` by the CLI).
 * Runtime does not write project files — see ``workspaceBootstrap.ts``.
 *
 * Merge is **shallow** per layer: if you add a top-level ``ai:`` block, it replaces the entire prior
 * ``ai`` map from earlier layers — include ``system_prompt`` there if you nest under ``ai``.
 * Top-level ``model`` / ``system_prompt`` are safe small overrides.
 */

export const DEFAULT_AGLOOM_YAML = `# Agloom — https://github.com/HELLOMEDHIRA/agloom
# CLI merges layers (see agloom_cli/docs/config.md): ~/.agloom → walk-up → --config → other CLI flags.
# multiline is YAML-only (no CLI flag); omit for default true (blank Enter sends). Routing pattern is chosen by the runtime, not configurable here.
#
# Defaults you usually edit (restart reloads YAML; no code path overwrites your file):
#   • model / ai.model          — provider:id (e.g. groq:meta-llama/llama-3.3-70b-versatile)
#   • ai.system_prompt          — default persona (or top-level system_prompt: | …)
#   • mcp.servers               — agsuperbrain → .agloom/mcp/agsuperbrain.yaml (stdio MCP; agsuperbrain CLI on PATH)
#   • .agloom/rules/            — drop *.md / *.mdc rule files; optional rules.dir if you relocate

ai:
  name: agloom
  model: auto
  system_prompt: |
    You are an autonomous AI programming assistant built with agloom.

    ## Your Capabilities

    You have access to tools for:

    - File operations: read, write, list, search, create, remove files and directories
    - Shell commands: execute commands in the terminal
    - Web search: search the web for documentation, bugs, or solutions
    - HTTP requests: make API calls when needed
    - Task planning: break down complex tasks into steps
    - Working directory: navigate and manage project context

    ## Guidelines

    1. Always prefer existing code - Don't suggest rewriting unless necessary
    2. Be concise - Give focused answers, not lengthy explanations
    3. Think step-by-step - For complex tasks, plan before executing
    4. Use tools wisely - Check file context before modifying
    5. Handle errors - gracefully explain what went wrong
    6. Respect user privacy - Don't log or store sensitive data

    ## Code Style

    - Follow existing conventions in the codebase
    - Use meaningful variable names
    - Add comments for complex logic
    - Keep functions small and focused

    ## Error Handling

    When you make mistakes or hit dead ends:

    - Acknowledge the error clearly
    - Explain what happened and why
    - Show what you tried and the outcome
    - Offer the next best approach

    ## Communication

    - Use markdown for code blocks
    - Show actual vs expected behavior for bugs
    - Suggest specific fixes
    - Ask clarification when requirements are unclear

    Remember: You're collaborating with a human. They control the session, you assist.

mcp:
  servers:
    - agsuperbrain:mcp/agsuperbrain.yaml

tools:
  dir: ''
  disabled: []
  # When true (default), the npm CLI passes --with-cli-tools to the Python runtime.
  cli_enabled: true

memory:
  enabled: true
  max_turns: 50
  auto_summarize: true

skills:
  enabled: true
  max_skills: 30

rules:
  dir: ''
  refresh: false

execution:
  max_concurrent: 4
  max_retries: 2
  llm_timeout: 120.0
  classifier_timeout: 30.0

safety:
  require_approval: true
  auto_approve: ''
`
