# MCP, memory & harness

This page covers **three optional layers** exposed through **`agloom-runtime`**: MCP servers, session/long-lived storage defaults, and the **harness** tools around progress + git.

## MCP servers

Pass MCP definitions from the CLI:

```bash
agloom --mcp fs:/abs/path/mcp/filesystem.yaml
```

YAML merges into **`MCPServerConfig`** (Python). In **`agloom.yaml`** use either strings (`name:path`) or objects with `name` + `config` keys; relative paths resolve against the YAML file directory.

**Catalog & specs:** see [MCP Servers](../agloom/features/mcp.md) and the upstream [MCP registry](https://github.com/modelcontextprotocol/servers).

Example skeleton:

```yaml
name: demo-fs
transport: stdio
command: npx
args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

## Session memory

Runtime flags (`serve`):

| Flag | Role |
| --- | --- |
| `--memory <type>` | Backend hint (`sqlite`, `in-memory`, `none`, …). |
| `--memory-path <path>` | SQLite file when using sqlite session memory. |
| `--no-memory` | Minimal in-process memory. |
| `--session-max-turns` | Rolling window size. |
| `--summarizer-model` | Separate model id for summarization. |
| `--no-auto-summarize` | Disable rolling summarization. |

Defaults integrate with LangGraph stores opened by the runtime (`serve_cli.py`, `__main__.py`).

## LangGraph store & harness

Separate from AGP EventStore:

| Flag | Role |
| --- | --- |
| `--agent-store <none\|memory\|sqlite\|sqlite-sync>` | Long-lived agent store (skills, LT memory tools). Default sqlite async. |
| `--agent-store-path <path>` | SQLite path (default `.agloom/graph_store.sqlite`). |
| `--no-harness` | Disable harness tools (progress + git) while keeping store-backed features available. |

**Harness** emits structured progress (`agloom-progress.json` convention) and git-aware helpers — see [Long-running harness](../agloom/features/harness.md).

## SQLite defaults

Typical workspace artifacts:

| Path | Purpose |
| --- | --- |
| `.agloom/graph_store.sqlite` | LangGraph async store (default) |
| `.agloom/session_memory.sqlite` | Session memory when `--memory sqlite` |
| `.agloom/agp_events.db` | AGP EventStore when `--store sqlite` (CLI default) |

Tune paths via flags or YAML (`store_path`, `memory_path`) plus pass-through **`--`**.

## See also

- [Configuration](config.md)
- [Flags](flags.md)
- [Runtime architecture](../agloom/runtime/architecture.md)
