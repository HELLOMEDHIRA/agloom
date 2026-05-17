# Observability API (`agloom.observability`)

This package persists **AGP envelopes** (SQLite), aggregates **session metrics**, exposes **replay**, and mounts an optional **FastAPI** router for dashboards or internal tools.

## Store

```python
from agloom.observability import ObservabilityStore

store = await ObservabilityStore.open("agloom_obs.db")
await store.ingest(envelope_dict)  # same shape as AGP JSON objects
```

**`ObservabilityStore`** is the public name for the SQLite implementation; rows surface as **`SessionSummary`**, **`EventRow`**, etc.

## Metrics and replay

- **`MetricsAggregator`** — rollups per session (tokens, costs, graph summaries — see source for fields).
- **`ReplayEngine`** — drives SSE-style replay from stored events.

## FastAPI router

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from agloom.observability import ObservabilityStore, make_obs_router, push_live_event


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = await ObservabilityStore.open("agloom_obs.db")
    app.include_router(make_obs_router(store), prefix="/observe")
    yield
    # optional: await store.close() when exposed by your store version


app = FastAPI(lifespan=lifespan)


# After each runtime emit, fan out to subscribers of GET /observe/live
def on_emit(envelope_dict: dict) -> None:
    push_live_event(envelope_dict)
```

Endpoints include session listing, paginated events, per-session metrics/graph/workers, **`DELETE`** purge, **`GET /observe/live`** (SSE), and **`POST /observe/ingest`**. Full list is documented in **`agloom/observability/api.py`**.

**Dependency:** FastAPI/Starlette are required only when you import **`make_obs_router`** / run the HTTP surface — keep ingest-only paths lightweight if you prefer not to mount HTTP.

## Estimated cost on the wire

When a provider omits dollar amounts, the AGP translator fills **`metric.cost`** with a coarse heuristic (`estimated: true` on the wire). Not suitable for billing.

## See also

- [Observability architecture](../observability/architecture.md)
- [Observability & LangSmith](../features/observability.md) — tracing product integration (complementary to this HTTP store)
