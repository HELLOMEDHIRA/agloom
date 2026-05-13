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

| Flag          | Default     | Description                                                       |
| ------------- | ----------- | ----------------------------------------------------------------- |
| `--transport` | `stdio`     | `stdio` or `ws` (WebSocket; requires `pip install 'agloom[ws]'`). |
| `--host`      | `127.0.0.1` | WebSocket bind address.                                           |
| `--port`      | `8765`      | WebSocket port.                                                   |
| `--session`   | *(auto)*    | Fixed AGP session id (replay key).                                |

### Event & agent stores

| Flag                 | Default                      | Description                                                                    |
| -------------------- | ---------------------------- | ------------------------------------------------------------------------------ |
| `--store`            | `none`                       | AGP EventStore: `none`, `memory`, `sqlite`.                                    |
| `--store-path`       | *(see help)*                 | SQLite path when `--store=sqlite`.                                             |
| `--agent-store`      | `sqlite`                     | LangGraph store: `none`, `memory`, `sqlite`, `sqlite-sync`.                    |
| `--agent-store-path` | `.agloom/graph_store.sqlite` | SQLite file for agent store.                                                   |
| `--no-harness`       | off                          | Disable harness tools (progress + git); skills/memory remain if store enabled. |

### CLI tools (filesystem / shell / web)

| Flag                      | Description                                             |
| ------------------------- | ------------------------------------------------------- |
| `--with-cli-tools`        | Inject built-in CLI tools (off by default).             |
| `--cli-tools-working-dir` | Sandbox root (default `.`).                             |
| `--cli-tools-no-shell`    | Disable `execute`, `bash`, `bash_background*`.          |
| `--cli-tools-no-network`  | Disable `fetch_url`, `read_url_markdown`, `web_search`. |
| `--cli-tools-no-sandbox`  | Allow paths outside `working-dir` (**dangerous**).      |

### HITL allowlist persistence

| Flag                          | Description                                                                                                                       |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `--hitl-allowlist-path`       | JSON file for persistent tool allowlist (`decision=allowlist`). Default if omitted: `.agloom/hitl_tool_allowlist.json` under cwd. |
| `--no-hitl-allowlist-persist` | Do not load/save allowlist file (memory-only).                                                                                    |

### Observability HTTP API

| Flag         | Default         | Description                                                            |
| ------------ | --------------- | ---------------------------------------------------------------------- |
| `--obs`      | off             | Enable observability SQLite + HTTP API.                                |
| `--obs-db`   | `agloom_obs.db` | Observability database path.                                           |
| `--obs-port` | `8766`          | HTTP port for REST + SSE (`/observe/...`).                             |
| `--otel`     | off             | OpenTelemetry tracing (`pip install 'agloom[otel]'`; OTLP or console). |

### Stdio / WebSocket tuning

| Flag                     | Default   | Description                                                  |
| ------------------------ | --------- | ------------------------------------------------------------ |
| `--heartbeat-interval`   | `30`      | Seconds between `session.heartbeat` on stdio (`0` disables). |
| `--ws-token`             | *(none)*  | Require `Authorization: Bearer <token>` on WS handshake.     |
| `--ws-max-message-bytes` | `4194304` | Max inbound WS frame size.                                   |
| `--ws-max-queue`         | `64`      | Inbound queue depth.                                         |
| `--ws-subprotocol`       | `agp-v1`  | Subprotocol name (empty string to disable negotiation).      |

## See also

- [CLI tools feature doc](../features/cli-tools.md) — tool reference.
- [Runtime architecture](architecture.md) — design overview.
- [Observability metrics and probes](../guides/observability-metrics.md) — `/observe/healthz`, `/readyz`, `/metrics`, `--otel`.
