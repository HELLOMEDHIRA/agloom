# agloom CLI

The **agloom CLI** is a terminal workspace for agloom agents: live streaming, tool traces, reasoning steps, HITL approvals, and session metrics — powered by the same **AGP** protocol as the web app.

```bash
pip install agloom          # Python runtime (agloom-runtime)
npm install -g agloom-cli   # Terminal UI
agloom -m groq:llama-3.3-70b-versatile
```

!!! note "Same docs, two paths"
    On [Read the Docs](https://agloom.readthedocs.io), these pages live under **`_packages/agloom_cli/`** after the docs build. On GitHub, they are in [`agloom_cli/docs/`](https://github.com/HELLOMEDHIRA/agloom/tree/main/agloom_cli/docs).

---

## What you get without writing orchestration code

| You do | The CLI does |
| ------ | ------------- |
| Type a question or pipe a diff | Classifies the task and picks an execution pattern |
| Approve or deny tool prompts | Enforces HITL for risky tools (configurable allowlist) |
| Watch the right sidebar | Streams **tokens**, **wire notes**, and **tool results** in full |
| Use `/retry`, `/undo`, `/checkpoint` | Session memory + harness workflows when enabled |

The CLI does **not** embed Python in Node — it spawns **`agloom-runtime`** and speaks **newline-delimited JSON (AGP)** on stdio.

---

## Prerequisites

- **Python 3.12+** with `pip install agloom` (`agloom-runtime` on `PATH`)
- **Node.js ≥ 24.15** ([`package.json` engines](https://github.com/HELLOMEDHIRA/agloom/blob/main/agloom_cli/package.json))

!!! warning "Install Python first"
    Without the PyPI package, the CLI exits with **Cannot find agloom-runtime**. Set `AGLOOM_RUNTIME` only for a custom interpreter path.

---

## Install

```bash
pip install agloom
npm install -g agloom-cli
agloom
```

From a git checkout:

```bash
cd agloom_cli && npm install && npm run build && npm start
```

---

## First run

```bash
export GROQ_API_KEY=gsk_...
agloom -m groq:meta-llama/llama-3.3-70b-versatile
```

| Mode | When |
| ---- | ---- |
| **Interactive TUI** | `agloom` with no prompt (TTY) |
| **Direct** | Positional prompt, `-p` / `-q`, or stdin pipe |

---

## Documentation map

| Page | Purpose |
| ---- | ------- |
| [Quickstart](quickstart.md) | Five-minute tour |
| [Models & providers](models.md) | `--model` prefixes, env keys, catalogs |
| [CLI flags](flags.md) | Every npm option |
| [Config & environment](config.md) | `agloom.yaml`, env vars |
| [Direct mode](direct-mode.md) | Scripts, `--json`, exit codes |
| [Interactive UI](interactive.md) | Layout, slash commands, metrics sidebar |
| [Tools & HITL](tools-hitl.md) | Built-in tools and approvals |
| [MCP, memory & harness](mcp-memory-harness.md) | MCP, session memory, long-running harness |
| [Recipes](recipes.md) | Copy-paste workflows |
| [Troubleshooting](troubleshooting.md) | Runtime, models, HITL, tokens, stray JSON |
| [AGP wire reference](reference.md) | Build custom clients on stdio NDJSON |

**Python library docs:** [agloom.readthedocs.io — Python package](https://agloom.readthedocs.io/en/latest/_packages/agloom/)

---

## Provider discovery

```bash
agloom --list-providers
agloom --resolve-model "bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0"
```

Same as `agloom-runtime providers list` / `resolve`.

---

## See also

- [Runtime CLI (Python)](../agloom/runtime/cli.md) — `agloom-runtime serve` flags
- [AGP specification](../agloom/protocol/agp.md)
- [Integration overview (library)](../agloom/guides/developer-overview.md)
