# CLI flags

Flags are parsed by the **`agloom`** CLI entrypoint. Most forward to **`agloom-runtime serve`**; anything after a lone **`--`** is appended verbatim to the Python argv.

Get the live list:

```bash
agloom --help
```

## Session / AGP store

| Flag                  | Example      | Meaning                                                   |                  |                                                      |
| --------------------- | ------------ | --------------------------------------------------------- | ---------------- | ---------------------------------------------------- |
| `-t, --thread <id>`   | `-t t_dev`   | LangGraph thread id for invocations (default: generated). |                  |                                                      |
| `-s, --session <id>`  | `-s replay1` | AGP session id (`agloom-runtime --session`).              |                  |                                                      |
| `--store <none\       | memory\      | sqlite>`                                                  | `--store sqlite` | Event store for replay/resume (CLI default: sqlite). |
| `--store-path <path>` |              | SQLite path when `--store=sqlite`.                        |                  |                                                      |

## Model / agent

| Flag                          | Example                  | Meaning                                                   |
| ----------------------------- | ------------------------ | --------------------------------------------------------- |
| `-m, --model <id>`            | `-m openai:gpt-4o`       | Prefixed model id (see [Models](models.md)).              |
| `--provider <slug>`           | `--provider huggingface` | Force provider when the id is ambiguous.                  |
| `--api-key-env <VAR>`         | `--api-key-env MYKEY`    | Map secret from `VAR` to the provider’s standard env key. |
| `-T, --temperature <n>`       | `-T 0.2`                 | Sampling temperature.                                     |
| `--max-tokens <n>`            |                          | Max output tokens when supported.                         |
| `--system-prompt <text>`      |                          | Inline system prompt.                                     |
| `--system-prompt-file <path>` |                          | System prompt from UTF-8 file.                            |

TUI **`multiline`** is not a CLI flag — set it in **`agloom.yaml`** (see [Config](config.md)). Execution routing is chosen by the runtime; it is **not** overridable from YAML, flags, or slash commands.

## Provider discovery

| Flag                     | Meaning                                                                |
| ------------------------ | ---------------------------------------------------------------------- |
| `--list-providers`       | Print curated registry table and exit (calls Python `providers list`). |
| `--resolve-model <spec>` | Dry-run routing / env snapshot and exit (`providers resolve`).         |

## MCP

| Flag                | Example                                         |
| ------------------- | ----------------------------------------------- |
| `--mcp <name:path>` | Repeatable; YAML merged into MCP server config. |

## Memory / skills / summarization

| Flag                      | Meaning                                    |
| ------------------------- | ------------------------------------------ |
| `--memory <type>`         | `in-memory`, `none`, `sqlite`, … |
| `--memory-path <path>`    | SQLite path for session memory.            |
| `--skills-dir <path>`     | Skills directory.                           |
| `--summarizer-model <id>` | Model id for summarization.                |
| `--no-auto-summarize`     | Disable auto summarization.                |
| `--session-max-turns <n>` | Rolling window size (`--max-turns` alias). |

## CLI tools (sandbox)

Default npm behavior enables **`--with-cli-tools`** with working dir = cwd unless opted out.

| Flag                 | Forwards to runtime      |
| -------------------- | ------------------------ |
| `--no-cli-tools`     | Omit `--with-cli-tools`. |
| `--no-shell-tool`    | `--cli-tools-no-shell`   |
| `--no-network-tools` | `--cli-tools-no-network` |
| `--unrestricted`     | `--cli-tools-no-sandbox` |

## Direct mode

| Flag                  | Meaning                                    |
| --------------------- | ------------------------------------------ |
| `[prompt]`            | Positional one-shot prompt.                |
| `-p, --prompt <text>` | Alternative prompt source.                 |
| `-q, --quiet`         | Assistant text only (no protocol framing). |
| `--json`              | NDJSON AGP events on stdout.               |
| `--no-stream`         | Buffer until assistant message completes.  |
| `--no-color`          | Strip ANSI in direct output.               |
| `--no-banner`         | Suppress ASCII banner.                     |
| `--auto-approve`      | Auto-approve HITL (**dangerous**).         |
| `--auto-reject`       | Auto-reject HITL prompts.                  |
| `--hitl-tty`          | Interactive HITL on a TTY in direct mode.  |

## Config introspection

| Flag              | Meaning                                                  |
| ----------------- | -------------------------------------------------------- |
| `--config <path>` | Explicit `agloom.yaml` (overrides walk-up discovery).    |
| `--print-config`  | Print merged YAML + CLI + env snapshot as JSON and exit. |

Example:

```bash
agloom --print-config
```

Shows resolved model, store, MCP specs, and which YAML files contributed.

## UI-only

| Flag | Meaning |
| --- | --- |
| `--diag` | Open stderr diagnostic pane on startup. |
| `--theme <dark\|light>` | Terminal palette hint (default: dark). |
| `--capture <path>` | Append all AGP events as NDJSON to a file during the session. |

## Subcommands

| Command | Action |
| --- | --- |
| `agloom init` | Scaffold `.agloom/` directory and starter YAML. |
| `agloom sessions` | Open an **interactive picker** (arrow keys, Enter) to choose a past session and resume it. |
| `--list-sessions` | Same picker from the default command: `agloom --list-sessions` (also accepts legacy `--sessions`). |
| `agloom clean` | Remove `.agloom/`, `.agsuperbrain/`, `agloom-progress.json`, and prune related lines from `.gitignore` (does **not** delete `agloom.yaml`). |
| `agloom upgrade` | Compare installed versions against npm/PyPI latest. |
| `agloom eval` | Forward to `agloom-runtime eval` for evaluation runs. |

## Pass-through (`--`)

Forward native runtime flags not wrapped by Commander:

```bash
agloom --session dev -- --obs --obs-port 8766
agloom -- --agent-store none
```

See [Runtime CLI](../agloom/runtime/cli.md) for the Python flag reference.
