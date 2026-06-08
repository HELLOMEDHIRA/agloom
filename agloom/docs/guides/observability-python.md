# Observability API

Build **session dashboards**, **replay**, and **live feeds** by persisting AGP events to SQLite and optionally exposing a small HTTP API.

---

## Store events

```python
from agloom.observability import ObservabilityStore

store = await ObservabilityStore.open("agloom_obs.db")
await store.ingest(envelope_dict)  # same JSON shape as one AGP NDJSON line
```

Each ingested envelope is keyed by **session** and **sequence** so you can list sessions, paginate history, and compute rollups.

---

## Metrics and replay

| Component | Purpose |
| --------- | ------- |
| Metrics aggregator | Per-session token/cost/graph summaries |
| Replay engine | SSE-style replay of stored events for a session |

Wire these into your own worker after each `agloom-runtime` emit, or call **`push_live_event`** from a FastAPI app for live subscribers.

---

## FastAPI router (optional)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from agloom.observability import ObservabilityStore, make_obs_router, push_live_event

@asynccontextmanager
async def lifespan(app: FastAPI):
    store = await ObservabilityStore.open("agloom_obs.db")
    app.include_router(make_obs_router(store), prefix="/observe")
    yield

app = FastAPI(lifespan=lifespan)

def on_emit(envelope_dict: dict) -> None:
    push_live_event(envelope_dict)
```

Typical routes: session list, paginated events, per-session metrics, graph/worker summaries, live SSE (`GET /observe/live`), ingest (`POST /observe/ingest`), purge.

FastAPI is only required when you mount the HTTP router — ingest-only pipelines stay lightweight.

---

## Estimated cost on the wire

When a provider omits dollar amounts, **`metric.cost`** may include a coarse estimate (`estimated: true`). Use provider billing APIs for authoritative charges.

---

## See also

- [Observability architecture](../observability/architecture.md)
- [Observability & LangSmith](../features/observability.md)
- [AGP specification](../protocol/agp.md)
