# AGP from Python

The [**AGP specification**](../protocol/agp.md) describes the JSON wire format (event types, commands, versioning). This page shows how to **use that contract in Python** without reimplementing parsers.

---

## Three integration levels

| Level | When to use | API |
| ----- | ----------- | --- |
| **Easiest** | You already have an agent; want typed events | `agent.astream_agp_events()` |
| **Bridge** | You own stdout/WebSocket and one prompt per invocation | `run_invocation` + `SessionEmitter` |
| **Full control** | Custom servers, replay stores, schema export | `agloom.protocol` models + stores |

Most application code should stop at **`astream_agp_events`** unless you are building a new client.

---

## Level 1 — Stream AGP from an existing agent

```python
async for evt in agent.astream_agp_events(
    "Explain Mars",
    thread_id="demo",
    session_id="sess_demo",
):
    if evt.type == "token.delta":
        print(evt.data.text, end="", flush=True)
    elif evt.type == "session.closed":
        break
```

Each `evt` is a typed envelope (`token.delta`, `tool.call.start`, `metric.tokens`, …).  
No manual session lifecycle — the stream opens and closes the session for you.

Guide: [Streaming & events](../features/streaming.md).

---

## Level 2 — Emit NDJSON yourself

```python
from agloom.protocol import SessionEmitter

emitter = SessionEmitter(session="s1", thread="t1", writer=sys.stdout.write)
emitter.emit_session_opened(runtime_version="0.1.0", protocol_version="1")
# ... run agent, translate progress to emit_* calls ...
emitter.emit_session_closed(reason="completed")
```

For a full turn wired to `create_agent`, prefer **`run_invocation`** — see [Embedding the runtime](embedding-runtime.md).

---

## Level 3 — Parse inbound lines

After `json.loads(line)`:

```python
import json
from agloom.protocol import event_adapter

env = event_adapter.validate_python(json.loads(line))
print(env.type, env.data)
```

Inbound **commands** (`command.invoke`, `command.hitl.respond`, …) use the parallel **`command_adapter`**.

**Forward compatibility:** unknown `type` values should be ignored or logged, not crash your UI.

---

## Replay and persistence

| Store | Use case |
| ----- | -------- |
| In-memory | Unit tests, short demos |
| SQLite | Resume sessions, observability dashboards |

Attach a store to `SessionEmitter` when clients need **`command.session.resume`**.

---

## Schema for other languages

Export the machine-readable catalog:

```bash
python -m agloom.protocol.schema --out agp-schema.json
```

The checked-in **`agp-schema.json`** in the repo is the source of truth for code generators. Human-readable field docs remain in [AGP — Agloom Protocol](../protocol/agp.md).

---

## See also

- [Embedding the runtime](embedding-runtime.md) — `run_invocation` lifecycle  
- [Wire tokens & metric.tokens](../features/wire-tokens.md) — token accounting on the wire  
- [Observability API](observability-python.md) — FastAPI + SSE replay
