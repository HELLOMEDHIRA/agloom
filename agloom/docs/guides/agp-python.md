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

When handling **`command.invoke`** with file attachments in your own transport, decode and stage files with **`agloom.runtime.attachment_stage.prepare_invoke_command`** (same logic as stdio/WebSocket serve).

## Replay and persistence

- **`MemoryEventStore`** — in-process ring buffer for tests.
- **`SqliteEventStore`** — durable store for **`command.session.resume`** style replay (used by the runtime when configured).

Schema export for external code generators: **`build_schema`**, **`write_schema`** in **`agloom.protocol.schema`**; the checked-in artifact is **`agloom/docs/protocol/agp-schema.json`**.

### Maintaining client parsers

When you add a wire field that **clients must parse**, update in lockstep:

1. Pydantic models in **`agloom.protocol.events`** / **`commands`**
2. **`agloom/tests/fixtures/agp_wire_required_keys.json`** (minimal required `data` keys)
3. **`agp-schema.json`** via `python -m agloom.protocol.schema`
4. TypeScript **`AGP_WIRE_DATA_SCHEMAS`** in **`agloom_cli`** and **`agloom_web`** (see each package’s `agpCatalogSync` test)

The [AGP specification](../protocol/agp.md) stays the human-readable contract; avoid duplicating implementation names there.

## In-process parity with the wire

If you do **not** want to manage an emitter but need **typed `Envelope` instances** (same classes as NDJSON lines), use **`UnifiedAgent.astream_agp_events()`** — see [Streaming & events](../features/streaming.md).

## See also

- [Embedding the runtime](embedding-runtime.md) — **`run_invocation`** ties **`UnifiedAgent`** to **`SessionEmitter`**
