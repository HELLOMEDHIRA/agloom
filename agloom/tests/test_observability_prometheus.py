"""Observability ``/observe/metrics`` Prometheus text."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from agloom.observability.api import make_obs_router
from agloom.observability.store.sqlite import SQLiteObservabilityStore


@pytest.mark.asyncio
async def test_observe_metrics_exposes_gauges(tmp_path) -> None:
    path = str(tmp_path / "prom.db")
    store = await SQLiteObservabilityStore.open(path)
    try:
        app = FastAPI()
        app.include_router(make_obs_router(store), prefix="/observe")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/observe/metrics")
        assert r.status_code == 200
        text = r.text
        assert "agloom_up 1" in text
        assert "agloom_obs_store_sessions" in text
        assert "agloom_obs_live_subscribers" in text
    finally:
        await store.close()
