# CLI flags

Flags are parsed by the **`agloom`** CLI entrypoint. Most forward to **`agloom-runtime serve`**; anything after a lone **`--`** is appended verbatim to the Python argv.

Get the live list:

```bash
agloom --help
```

## Session / AGP store

| Flag | Example | Meaning |
| --- | --- | --- |
| `-t, --thread <id>` | `-t t_dev` | LangGraph thread id (default: generated). |
| `-s, --session <id>` | `-s replay1` | AGP session id for replay/resume. |
| `--store <none\ | memory\ | sqlite>` |
| `--store-path <path>` | | SQLite path when `--store=sqlite`. |

## Model / agent

| Flag | Example | Meaning |
| --- | --- | --- |
| `-m, --model <id>` | `-m openai:gpt-4o` | Prefixed model id (see [Models](models.md)). |
| `--provider <slug>` | `--provider huggingface` | Force provider when the id is ambiguous. |
| `--api-key-env <VAR>` | `--api-key-env MYKEY` | Map secret from `VAR` to the provider’s standard env key. |
| `-T, --temperature <n>` | `-T 0.2` | Sampling temperature. |
| `--max-tokens <n>` | | Max output tokens when supported. |
| `--system-prompt <text>` | | Inline system prompt. |
| `--system-prompt-file <path>` | | System prompt from UTF-8 file. |

TUI **`multiline`** is not a CLI flag — set it in **`agloom.yaml`** (see [Config](config.md)). Execution routing is chosen by the runtime; it is **not** overridable from YAML, flags, or slash commands.

## Provider discovery

| Flag | Meaning |
| --- | --- |
| `--list-providers` | Print curated registry table and exit (calls Python `providers list`). |
| `--resolve-model <spec>` | Dry-run routing / env snapshot and exit (`providers resolve`). |

## MCP

| Flag | Example |
| --- | --- |
| `--mcp <name:path>` | Repeatable; YAML merged into MCP server config. |

## Memory / skills / summarization

| Flag | Meaning |
| --- | --- |
| `--memory <type>` | `in-memory`, `none`, `sqlite`, … |
| `--memory-path <path>` | SQLite path for session memory. |
| `--skills-dir <path>` | Skills **disk mirror** directory. When omitted, `agloom-runtime` defaults to **`.agloom/skills`** under the process working directory so learned skills appear as files. |
| `--summarizer-model <id>` | Model id for summarization. |
| `--no-auto-summarize` | Disable auto summarization. |
| `--session-max-turns <n>` | Rolling window size (`--max-turns` alias). |

There is **no** `--no-memory` or `--no-skills` flag on the npm CLI or `agloom-runtime serve`; YAML `memory.enabled: false` / `skills.enabled: false` is ignored for disabling those systems (see [Config](config.md)).

## Execution / harness (`create_agent` via YAML)

The npm CLI does **not** wrap every runtime execution flag. Configure via **`.agloom/agloom.yaml`** (merged into runtime argv) or pass-through after `--`:

| YAML block | Runtime argv (via merge) | `create_agent` |
| --- | --- | --- |
| `execution.llm_timeout` | `--llm-timeout` | `llm_timeout` |
| `execution.classifier_timeout` | `--turn-planner-timeout` | `turn_planner_timeout` |
| `execution.react_graph_timeout` | `--react-graph-timeout` | `react_graph_timeout` |
| `execution.react_recursion_limit` | `--react-recursion-limit` | `react_recursion_limit` |
| `harness.project_name` / `goal` | `--harness-project-name`, `--harness-goal` | `harness_metadata` |
| `harness.enabled: false` | `--no-harness` | `harness=False` |
| `safety.require_approval: false` | `--no-require-tool-approval` | `require_tool_approval_for_cli_tools=False` |

```bash
# Passthrough when you need a flag not wrapped by Commander:
agloom -- --llm-timeout 800 --turn-planner-timeout 120
```

Agent behavior env vars (`AGLOOM_LLM_TIMEOUT`, `AGLOOM_HARNESS_ENABLED`, …) are **not** supported — see [Config](config.md).

## CLI tools (sandbox)

Default npm behavior enables **`--with-cli-tools`** with working dir = cwd unless opted out.

| Flag | Forwards to runtime |
| --- | --- |
| `--no-cli-tools` | Omit `--with-cli-tools`. |
| `--no-harness` | Forward `--no-harness` (disable progress/git harness tools). |
| `--agent-store <kind>` | LangGraph store: `none`, `memory`, `sqlite`, `sqlite-sync` (runtime default: `sqlite`). |
| `--agent-store-path <path>` | SQLite path when `--agent-store` is sqlite (default `.agloom/graph_store.sqlite`). |
| `--no-shell-tool` | `--cli-tools-no-shell` |
| `--no-network-tools` | `--cli-tools-no-network` |
| `--unrestricted` | `--cli-tools-no-sandbox` |

## Direct mode

| Flag | Meaning |
| --- | --- |
| `[prompt]` | Positional one-shot prompt. |
| `-p, --prompt <text>` | Alternative prompt source. |
| `-q, --quiet` | Assistant text only (no protocol framing). |
| `--json` | NDJSON AGP events on stdout. |
| `--no-stream` | Buffer until assistant message completes. |
| `--no-color` | Strip ANSI in direct output. |
| `--no-banner` | Suppress ASCII banner. |
| `--auto-approve` | Auto-approve HITL (**dangerous**). |
| `--auto-reject` | Auto-reject HITL prompts. |
| `--hitl-tty` | Interactive HITL on a TTY in direct mode. |

## Config introspection

| Flag | Meaning |
| --- | --- |
| `--config <path>` | Explicit `agloom.yaml` (overrides walk-up discovery). |
| `--print-config` | Print merged YAML + CLI + env snapshot as JSON and exit. |

Example:

```bash
agloom --print-config
```

Shows resolved model, store, MCP specs, and which YAML files contributed.

## UI-only

| Flag | Meaning |
| --- | --- |
| `--diag` | Open stderr diagnostic pane on startup. |
| `--theme <dark\ | light>` |
| `--capture <path>` | Append all AGP events as NDJSON to a file during the session. |

There is **no** tool-expand toggle flag — reasoning traces and tool results are **always shown in full** in the TUI.

## Subcommands

| Command | Action |
| --- | --- |
| `agloom init` | Scaffold `.agloom/` directory and starter YAML. |
| `agloom sessions` | Open an **interactive picker** (arrow keys, Enter) to choose a past session and resume it. |
| `--list-sessions` | Same picker from the default command: `agloom --list-sessions` (also accepts legacy `--sessions`). |
| `agloom clean` | Remove `.agloom/`, `.agsuperbrain/`, `agloom-progress.json`, and prune related lines from `.gitignore` (does **not** delete `agloom.yaml`). |
| `agloom eval` | Forward to `agloom-runtime eval` for evaluation runs. |

## Pass-through (`--`)

Forward native runtime flags not wrapped by Commander:

```bash
agloom --session dev -- --obs --obs-port 8766
agloom -- --agent-store none
```

See [Runtime CLI](../agloom/runtime/cli.md) for the Python flag reference.
