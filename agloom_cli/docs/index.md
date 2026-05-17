# agloom CLI

The **agloom CLI** (`npm install -g agloom-cli`) is a terminal client with a **React**-based interactive UI. It speaks **AGP** (newline-delimited JSON) over stdio to **`agloom-runtime`** from the PyPI **`agloom`** package.

!!! note "Same docs, two paths"
    **Browsing on GitHub?** These Markdown files live in the repo at [`agloom_cli/docs/`](https://github.com/HELLOMEDHIRA/agloom/tree/main/agloom_cli/docs). **On [Read the Docs](https://agloom.readthedocs.io)**, they are copied into **`_packages/agloom_cli/`** during the docs build so they sit next to the Python package pages — same content, different URL.

## Prerequisites

- **Python 3.12+** with `pip install agloom` so `agloom-runtime` is on your `PATH`.
- **Node.js >= 24.15** (see `agloom_cli/package.json` engines).

!!! warning "Install Python first"
    Without `agloom` from PyPI, the CLI exits with a clear **Cannot find agloom-runtime** message. Set `AGLOOM_RUNTIME` only if you point at a custom interpreter or wrapper.

## Install

```bash
pip install agloom
npm install -g agloom-cli
agloom
```

From a git checkout: `cd agloom_cli && npm install && npm run build && npm start`.

## First run

```bash
export GROQ_API_KEY=...   # or another provider — see [Models & providers](models.md)
agloom -m groq:meta-llama/llama-3.3-70b-versatile
```

- **Interactive TUI** opens when you run `agloom` with no prompt (and stdin is a TTY).
- **Direct mode** runs when you pass a positional prompt, `-p` / `-q`, or pipe stdin.

## Documentation map

| Page                                           | Purpose                                        |
| ---------------------------------------------- | ---------------------------------------------- |
| [Quickstart](quickstart.md)                    | 5-minute tour                                  |
| [Models & providers](models.md)                | `--model` prefixes, env keys, extras, catalogs |
| [CLI flags](flags.md)                          | Every npm CLI option                           |
| [Config & environment](config.md)              | `agloom.yaml`, discovery order, env vars       |
| [Direct mode](direct-mode.md)                  | Scripting, `--json`, exit codes                |
| [Interactive UI](interactive.md)               | TUI layout, status bar, slash commands         |
| [Tools & HITL](tools-hitl.md)                  | Built-in CLI tools, approvals, allowlist       |
| [MCP, memory & harness](mcp-memory-harness.md) | MCP configs, session memory, harness           |
| [Recipes](recipes.md)                          | Copy-paste workflows                           |
| [Troubleshooting](troubleshooting.md)          | Common errors                                  |
| [AGP wire reference](reference.md)             | Stdout/stderr AGP rules for CLI clients        |

**Full docs site:** [agloom.readthedocs.io — CLI section](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/).

## Provider discovery (Python)

```bash
agloom --list-providers
agloom --resolve-model "bedrock:anthropic.claude-3-5-sonnet-20241022-v2:0"
```

Same commands as `agloom-runtime providers list` and `agloom-runtime providers resolve <spec>`.

## See also

- [Runtime CLI (Python)](../agloom/runtime/cli.md) — all `agloom-runtime serve` flags
- [AGP specification](../agloom/protocol/agp.md)
- [LLM resolution (library)](../agloom/guides/llm-resolution.md)
