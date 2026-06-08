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

GET  /observe/healthz                           → liveness JSON
GET  /observe/readyz                            → readiness (SQLite store ping)
GET  /observe/metrics                           → minimal Prometheus text
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .metrics import MetricsAggregator
from .replay import ReplayEngine
from .store import SQLiteObservabilityStore

# ── Live event bus ─────────────────────────────────────────────────────────────
# In-process publish/subscribe using asyncio.Queue per subscriber.
# Envelopes pushed via `push_live_event()` are delivered to all /live SSE clients.

_live_subscribers: list[asyncio.Queue[dict | None]] = []
_live_subscribers_lock = threading.Lock()
_obs_api_logger = logging.getLogger(__name__)


def push_live_event(envelope: dict) -> None:
    """Call from the runtime after every emit to deliver to /live SSE clients."""
    with _live_subscribers_lock:
        subscribers = list(_live_subscribers)
    for q in subscribers:
        try:
            q.put_nowait(envelope)
        except asyncio.QueueFull:
            _obs_api_logger.warning(
                "observability live.drop: queue full (maxsize=%s) session=%s type=%s",
                q.maxsize,
                envelope.get("session"),
                envelope.get("type"),
            )


# ── Router factory ─────────────────────────────────────────────────────────────

def make_obs_router(store: SQLiteObservabilityStore) -> APIRouter:
    agg    = MetricsAggregator(store)
    replay = ReplayEngine(store)
    router = APIRouter(tags=["observability"])

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness for reverse proxies and orchestrators (no auth)."""
        return {"status": "ok", "service": "agloom-observability"}

    @router.get("/readyz")
    async def readyz() -> dict[str, str]:
        """Readiness: observability SQLite store accepts a trivial query."""
        try:
            await store.list_sessions(limit=1, offset=0)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"store_unready:{exc!s}") from exc
        return {"status": "ready", "service": "agloom-observability"}

    @router.get("/metrics")
    async def prometheus_text() -> Response:
        """Prometheus text expose (liveness + cheap store / in-process gauges)."""
        sessions_n = 0
        try:
            sessions_n = await store.session_count()
        except Exception:
            pass
        with _live_subscribers_lock:
            live_n = len(_live_subscribers)
        lines = [
            "# HELP agloom_up Process is serving observability routes.",
            "# TYPE agloom_up gauge",
            "agloom_up 1",
            "",
            "# HELP agloom_obs_store_sessions Rows in the observability sessions summary table.",
            "# TYPE agloom_obs_store_sessions gauge",
            f"agloom_obs_store_sessions {sessions_n}",
            "",
            "# HELP agloom_obs_live_subscribers Active SSE clients on /observe/live.",
            "# TYPE agloom_obs_live_subscribers gauge",
            f"agloom_obs_live_subscribers {live_n}",
            "",
        ]
        body = "\n".join(lines)
        return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")

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
    ) -> JSONResponse:
        event_types = [t.strip() for t in types.split(",")] if types else None
        rows = await store.get_events(
            session_id,
            limit=limit, offset=offset,
            after_seq=after_seq,
            event_types=event_types,
        )
        payload = [
            {"seq": r.seq, "type": r.event_type, "ts": r.ts, "data": r.payload.get("data", {}), "run_id": r.run_id}
            for r in rows
        ]
        headers: dict[str, str] = {}
        if len(rows) >= limit and rows:
            headers["X-Has-More"] = "true"
            headers["X-Next-After-Seq"] = str(rows[-1].seq)
        return JSONResponse(content=payload, headers=headers)

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
            event_types=["worker.spawned", "worker.completed", "worker.failed", "worker.halted"],
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
        with _live_subscribers_lock:
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
                with _live_subscribers_lock:
                    try:
                        _live_subscribers.remove(q)
                    except ValueError:
                        pass

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
