# Runtime CLI — `agloom-runtime serve`

Entry point: **`agloom-runtime`** (PyPI package **`agloom`**) → `python -m agloom.runtime serve`.

Subcommand **`serve`** runs the AGP bridge on **stdio** (default) or **WebSocket**.

## Quick examples

```bash
# Stdio (default) — used by agloom-cli
agloom-runtime serve --transport=stdio --store memory

# WebSocket — used by agloom_web
agloom-runtime serve --transport=ws --port 8765

# Built-in filesystem/shell tools + sandboxed cwd
agloom-runtime serve --with-cli-tools --cli-tools-working-dir .

# Observability REST + SSE
agloom-runtime serve --obs --obs-db ./obs.sqlite --obs-port 8766
```

## Flags (`serve`)

### Transport & session

| Flag | Default | Description |
| --- | --- | --- |
| `--transport` | `stdio` | `stdio` or `ws` (WebSocket; requires `pip install 'agloom[ws]'`). |
| `--host` | `127.0.0.1` | WebSocket bind address. |
| `--port` | `8765` | WebSocket port. |
| `--session` | *(auto)* | Fixed AGP session id (replay key). |

### Event & agent stores

| Flag | Default | Description |
| --- | --- | --- |
| `--store` | `none` | AGP EventStore: `none`, `memory`, `sqlite`. |
| `--store-path` | *(see help)* | SQLite path when `--store=sqlite`. |
| `--agent-store` | `sqlite` | LangGraph store: `none`, `memory`, `sqlite`, `sqlite-sync`. |
| `--agent-store-path` | `.agloom/graph_store.sqlite` | SQLite file for agent store. |
| `--no-harness` | off | Disable harness tools (progress + git); skills/memory remain if store enabled. |

### Execution (`create_agent` kwargs)

Mapped from **`agloom.yaml`** `execution.*` / `harness.*` / `safety.*` or explicit flags below — **not** from `AGLOOM_*` environment variables.

| Flag | Maps to `create_agent` |
| --- | --- |
| `--llm-timeout <sec>` | `llm_timeout` |
| `--turn-planner-timeout` / `--classifier-timeout` | `turn_planner_timeout` |
| `--react-graph-timeout` | `react_graph_timeout` |
| `--react-recursion-limit` | `react_recursion_limit` |
| `--max-concurrent` | `max_concurrent` |
| `--max-retries` | `max_retries` |
| `--no-memory-tools` | `enable_memory_tools=False` |
| `--harness-project-name` | `HarnessMetadata.project_name` |
| `--harness-goal` | `HarnessMetadata.goal` |
| `--no-require-tool-approval` | `require_tool_approval_for_cli_tools=False` |

Example YAML:

```yaml
execution:
  llm_timeout: 800
  classifier_timeout: 120
harness:
  project_name: incident-8842
  goal: Checkout latency RCA
```

See [All parameters](../configuration/parameters.md) and [CLI config](../../agloom_cli/config.md).

!!! note "CLI default differs"
    The **`agloom`** npm CLI passes **`--store sqlite`** by default so sessions can be listed and replayed. Bare **`agloom-runtime serve`** defaults to **`--store none`**. See [agloom_cli flags](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/flags/).

With default **`--agent-store=sqlite`**, async SQLite needs **`aiosqlite`**. If it is missing or the DB cannot be opened, the runtime uses an in-memory LangGraph store instead, logs one line to **stderr**, and keeps serving (no LT/harness persistence across restarts until fixed).

### CLI tools (filesystem / shell / web)

| Flag | Description |
| --- | --- |
| `--with-cli-tools` | Inject built-in CLI tools (off by default). |
| `--cli-tools-working-dir` | Sandbox root (default `.`). |
| `--cli-tools-no-shell` | Disable `execute`, `bash`, `bash_background*`. |
| `--cli-tools-no-network` | Disable `fetch_url`, `read_url_markdown`, `web_search`. |
| `--cli-tools-no-sandbox` | Allow paths outside `working-dir` (**dangerous**). |

### HITL allowlist persistence

| Flag | Description |
| --- | --- |
| `--hitl-allowlist-path` | JSON file for persistent tool allowlist (`decision=allowlist`). Default if omitted: `.agloom/hitl_tool_allowlist.json` under cwd. |
| `--no-hitl-allowlist-persist` | Do not load/save allowlist file (memory-only). |

### Observability HTTP API

| Flag | Default | Description |
| --- | --- | --- |
| `--obs` | off | Enable observability SQLite + HTTP API. |
| `--obs-db` | `agloom_obs.db` | Observability database path. |
| `--obs-port` | `8766` | HTTP port for REST + SSE (`/observe/...`). |
| `--otel` | off | OpenTelemetry tracing (`pip install 'agloom[otel]'`; OTLP or console). |

### Stdio / WebSocket tuning

| Flag | Default | Description |
| --- | --- | --- |
| `--heartbeat-interval` | `30` | Seconds between `session.heartbeat` on stdio (`0` disables). |
| `--ws-token` | *(none)* | Require `Authorization: Bearer <token>` on WS handshake. |
| `--ws-max-message-bytes` | `4194304` | Max inbound WS frame size. |
| `--ws-max-queue` | `64` | Inbound queue depth. |
| `--ws-subprotocol` | `agp-v1` | Subprotocol name (empty string to disable negotiation). |

## See also

- [CLI tools feature doc](../features/cli-tools.md) — tool reference.
- [Runtime architecture](architecture.md) — design overview.
- [Observability metrics and probes](../guides/observability-metrics.md) — `/observe/healthz`, `/readyz`, `/metrics`, `--otel`.
