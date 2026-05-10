"""
agloom.observability.api
─────────────────────────
FastAPI router providing the full observability REST + SSE surface.

Mount into the main runtime app::

    from agloom.observability.api import make_obs_router

    obs_store = await SQLiteObservabilityStore.open("agloom_obs.db")
    app.include_router(make_obs_router(obs_store), prefix="/observe")

Endpoints
─────────
GET  /observe/sessions                          → list of SessionSummary
GET  /observe/sessions/:sid                     → SessionSummary + event count
GET  /observe/sessions/:sid/events              → paginated AGP events
GET  /observe/sessions/:sid/metrics             → SessionMetrics
GET  /observe/sessions/:sid/graph               → graph node traces
GET  /observe/sessions/:sid/workers             → worker traces
GET  /observe/sessions/:sid/replay              → SSE replay stream
DELETE /observe/sessions/:sid                   → 204 purge

GET  /observe/live                              → SSE feed of all live events
GET  /observe/summary                           → global dashboard summary
POST /observe/ingest                            → internal ingest (single envelope)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from .metrics import MetricsAggregator
from .replay import ReplayEngine
from .store import SQLiteObservabilityStore

# ── Live event bus ─────────────────────────────────────────────────────────────
# In-process publish/subscribe using asyncio.Queue per subscriber.
# Envelopes pushed via `push_live_event()` are delivered to all /live SSE clients.

_live_subscribers: list[asyncio.Queue[dict | None]] = []


def push_live_event(envelope: dict) -> None:
    """Call from the runtime after every emit to deliver to /live SSE clients."""
    for q in _live_subscribers:
        try:
            q.put_nowait(envelope)
        except asyncio.QueueFull:
            pass  # slow consumer — drop rather than block runtime


# ── Router factory ─────────────────────────────────────────────────────────────

def make_obs_router(store: SQLiteObservabilityStore) -> APIRouter:
    agg    = MetricsAggregator(store)
    replay = ReplayEngine(store)
    router = APIRouter(tags=["observability"])

    # ── Sessions list ──────────────────────────────────────────────────────────

    @router.get("/sessions")
    async def list_sessions(
        limit:  int = Query(50,  ge=1, le=200),
        offset: int = Query(0,   ge=0),
        status: str | None = Query(None, pattern="^(open|closed|error)$"),
    ) -> list[dict]:
        sessions = await store.list_sessions(limit=limit, offset=offset, status=status)
        return [asdict(s) for s in sessions]

    # ── Session detail ─────────────────────────────────────────────────────────

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str) -> dict:
        summary = await store.get_session(session_id)
        if not summary:
            raise HTTPException(404, f"Session {session_id!r} not found")
        total_events = await store.get_event_count(session_id)
        return {**asdict(summary), "total_events": total_events}

    # ── Events ─────────────────────────────────────────────────────────────────

    @router.get("/sessions/{session_id}/events")
    async def get_events(
        session_id: str,
        limit:      int = Query(200, ge=1, le=1000),
        offset:     int = Query(0,   ge=0),
        after_seq:  int | None = Query(None),
        types:      str | None = Query(None, description="Comma-separated event types"),
    ) -> list[dict]:
        event_types = [t.strip() for t in types.split(",")] if types else None
        rows = await store.get_events(
            session_id,
            limit=limit, offset=offset,
            after_seq=after_seq,
            event_types=event_types,
        )
        return [{"seq": r.seq, "type": r.event_type, "ts": r.ts, "data": r.payload.get("data", {}), "run_id": r.run_id} for r in rows]

    # ── Metrics ────────────────────────────────────────────────────────────────

    @router.get("/sessions/{session_id}/metrics")
    async def get_metrics(session_id: str) -> dict:
        summary = await store.get_session(session_id)
        if not summary:
            raise HTTPException(404, f"Session {session_id!r} not found")
        metrics = await agg.compute(session_id)
        return _metrics_to_dict(metrics)

    # ── Graph trace ────────────────────────────────────────────────────────────

    @router.get("/sessions/{session_id}/graph")
    async def get_graph_trace(session_id: str) -> list[dict]:
        rows = await store.get_events(
            session_id,
            event_types=["graph.node.enter", "graph.node.exit"],
            limit=5000,
        )
        return [{"seq": r.seq, "type": r.event_type, "ts": r.ts, **r.payload.get("data", {})} for r in rows]

    # ── Worker traces ──────────────────────────────────────────────────────────

    @router.get("/sessions/{session_id}/workers")
    async def get_worker_traces(session_id: str) -> list[dict]:
        rows = await store.get_events(
            session_id,
            event_types=["worker.spawned", "worker.completed", "worker.failed"],
            limit=5000,
        )
        return [{"seq": r.seq, "type": r.event_type, "ts": r.ts, **r.payload.get("data", {})} for r in rows]

    # ── SSE Replay ─────────────────────────────────────────────────────────────

    @router.get("/sessions/{session_id}/replay")
    async def sse_replay(
        session_id: str,
        speed: float = Query(1.0, ge=0, le=100),
    ) -> StreamingResponse:
        summary = await store.get_session(session_id)
        if not summary:
            raise HTTPException(404, f"Session {session_id!r} not found")

        async def stream() -> AsyncIterator[str]:
            async for envelope in replay.replay(session_id, speed=speed):
                yield f"data: {json.dumps(envelope)}\n\n"
            yield "data: {\"type\":\"replay.done\"}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── SSE Live feed ──────────────────────────────────────────────────────────

    @router.get("/live")
    async def sse_live(request: Request) -> StreamingResponse:
        q: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=500)
        _live_subscribers.append(q)

        async def stream() -> AsyncIterator[str]:
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        envelope = await asyncio.wait_for(q.get(), timeout=15)
                        if envelope is None:
                            break
                        yield f"data: {json.dumps(envelope)}\n\n"
                    except TimeoutError:
                        yield ": heartbeat\n\n"
            finally:
                _live_subscribers.remove(q)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── Global summary ─────────────────────────────────────────────────────────

    @router.get("/summary")
    async def global_summary() -> dict:
        return await agg.global_summary()

    # ── Ingest (internal / testing) ────────────────────────────────────────────

    @router.post("/ingest", status_code=202)
    async def ingest_envelope(envelope: dict[str, Any]) -> dict:
        await store.ingest(envelope)
        push_live_event(envelope)
        return {"ok": True}

    # ── Delete session ─────────────────────────────────────────────────────────

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> Response:
        await store.delete_session(session_id)
        return Response(status_code=204)

    return router


# ── Helper ─────────────────────────────────────────────────────────────────────

def _metrics_to_dict(m: Any) -> Any:
    """Recursively convert dataclass tree to JSON-serialisable dict or list."""
    import dataclasses
    if dataclasses.is_dataclass(m):
        return {k: _metrics_to_dict(v) for k, v in dataclasses.asdict(m).items()}
    if isinstance(m, list):
        return [_metrics_to_dict(i) for i in m]
    return m
