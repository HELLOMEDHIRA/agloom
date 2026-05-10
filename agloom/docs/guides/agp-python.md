# AGP from Python (`agloom.protocol`)

The [**AGP specification**](../protocol/agp.md) describes the JSON wire format. This page shows how to work with that contract **in Python** using the shipped Pydantic models.

## Emitting AGP

- **`SessionEmitter`** — synchronous writer (e.g. **`sys.stdout.write`**). Each **`emit_*`** appends one NDJSON line when a **`writer`** is set; tests often capture bytes on a **`StringIO`**.
- **`AsyncSessionEmitter`** — asyncio queue + flush loop; used by **`RuntimeNode`** and WebSocket transports.

Low-level helpers: **`Envelope`**, **`new_event_id`**, **`now_utc`**, **`event_to_dict`**.

## Consuming AGP

- **`event_adapter`** — **`TypeAdapter`** for the discriminated union of all Phase-0 event types. Parse a decoded **`dict`** after JSON loading:

```python
import json
from agloom.protocol import event_adapter

line = '{"v":"1","id":"evt_...","type":"token.delta", ...}'
env = event_adapter.validate_python(json.loads(line))
```

- **`command_adapter`** — same idea for inbound **`Command`** variants (`command.invoke`, `command.session.resume`, …).

## Replay and persistence

- **`MemoryEventStore`** — in-process ring buffer for tests.
- **`SqliteEventStore`** — durable store for **`command.session.resume`** style replay (used by the runtime when configured).

Schema export for external code generators: **`build_schema`**, **`write_schema`** in **`agloom.protocol.schema`** (see repo **`scripts/`** and **`agloom/docs/protocol/agp-schema.json`**).

## In-process parity with the wire

If you do **not** want to manage an emitter but need **typed `Envelope` instances** (same classes as NDJSON lines), use **`UnifiedAgent.astream_agp_events()`** — see [Streaming & events](../features/streaming.md).

## See also

- [Embedding the runtime](embedding-runtime.md) — **`run_invocation`** ties **`UnifiedAgent`** to **`SessionEmitter`**
