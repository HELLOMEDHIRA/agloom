# CLI, web, and custom AGP clients

agloom ships three ways to **use** the same agent pipeline:

| Path | Best for |
| --- | --- |
| **Python library** (`create_agent`) | Embed in your API, notebook, or batch job |
| **CLI** (`agloom-cli`) | Terminal TUI, scripts, pipes, local dev |
| **Web workspace** (`agloom_web`) | Browser chat, harness task board, observability |

All three consume the same **Agloom Protocol (AGP)** event shapes when talking to **`agloom-runtime`**.

---

## Architecture

```text
┌─────────────────┐     AGP (NDJSON)      ┌──────────────────┐
│  agloom-cli     │ ◄──── stdio ────────► │                  │
└─────────────────┘                       │  agloom-runtime  │
┌─────────────────┐     AGP (WebSocket)   │  (Python bridge) │
│  agloom_web     │ ◄──── ws ───────────► │                  │
└─────────────────┘                       │  create_agent    │
┌─────────────────┐     AGP (stdio/ws)    │  pipeline        │
│  Your service   │ ◄────────────────────► │                  │
└─────────────────┘                       └──────────────────┘
```

The runtime does **not** reimplement orchestration — it forwards the in-process agent event stream as typed AGP envelopes.

---

## Feature parity

| Capability | Python (`astream_agp_events`) | CLI | Web |
| --- | --- | --- | --- |
| Streaming tokens | yes | yes | yes |
| Tool traces (full) | yes | yes | yes |
| Reasoning stream | yes | yes | yes |
| HITL approvals | callback | TTY prompts | inline UI |
| Harness ledger | `harness.synced` events | metrics sidebar | **Harness** tab |
| Harness git ops | tools / `command.harness.git` | `/checkpoint`, `/git` | `/checkpoint`, `/git` |
| Session memory | `thread_id` | default sqlite store | same runtime |
| Observability replay | DIY | limited | `/observe`, trace viewer |

---

## Harness defaults (important)

| How you run | Harness default |
| --- | --- |
| **`create_agent(...)`** in Python | **Off** — pass `harness=True` + `harness_metadata` + `store=` |
| **`agloom`** / **`agloom-runtime serve`** | **On** when a LangGraph agent store is open (default sqlite) |
| Disable at runtime | `--no-harness` or `harness.enabled: false` in YAML |

Wire signal: `runtime.ready.harness_enabled` → clients show **harness on/off** badge.

### Configuration (same contract everywhere)

Agent timeouts, harness metadata, and tool approval flow through **`create_agent` kwargs** — via Python directly, or via **`.agloom/agloom.yaml`** (`execution.*`, `harness.*`, `safety.*`) merged into `agloom-runtime serve` argv. Environment variables such as `AGLOOM_LLM_TIMEOUT` or `AGLOOM_HARNESS_ENABLED` are **not** supported.

See [Configuration contract](developer-overview.md#configuration-contract-single-source-of-truth) · [CLI config](../../agloom_cli/config.md) · [Runtime flags](../../agloom_cli/flags.md).

---

## Quick starts

### CLI

```bash
pip install agloom
npm install -g agloom-cli
export GROQ_API_KEY=gsk_...
agloom -m groq:llama-3.3-70b-versatile
```

Docs: [CLI overview](../../agloom_cli/index.md) · [MCP, memory & harness](../../agloom_cli/mcp-memory-harness.md)

### Web

```bash
agloom-runtime serve --transport=ws --port 8765
cd agloom_web && npm install && npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Docs: [Web overview](../../agloom_web/index.md)

### Custom client

```python
async for evt in agent.astream_agp_events("Hello", thread_id="demo"):
    if evt.type == "token.delta":
        print(evt.data.text, end="", flush=True)
```

Docs: [AGP specification](../protocol/agp.md) · [AGP from Python](agp-python.md) · [Embedding the runtime](embedding-runtime.md)

---

## Related

- [Integration overview](developer-overview.md) — three integration paths
- [Long-running harness](../features/harness.md) — ledger, focus injection, git tools
- [Production deployment](deployment.md) — Docker, reverse proxy, `VITE_AGP_WS_URL`
