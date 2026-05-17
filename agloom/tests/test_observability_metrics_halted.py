"""Observability metrics include cooperative worker halts."""

from __future__ import annotations

import pytest

from agloom.observability.metrics import MetricsAggregator
from agloom.observability.store import SQLiteObservabilityStore


@pytest.mark.asyncio
async def test_metrics_aggregator_records_worker_halted(tmp_path) -> None:
    db = tmp_path / "obs.sqlite"
    store = await SQLiteObservabilityStore.open(db)
    session_id = "s_halt_test"
    await store.ingest(
        {
            "session": session_id,
            "seq": 1,
            "type": "session.opened",
            "data": {},
        },
    )
    await store.ingest(
        {
            "session": session_id,
            "seq": 2,
            "type": "worker.halted",
            "data": {
                "worker_id": "w1",
                "name": "researcher",
                "reason": "HALT_ALL",
                "duration_ms": 120,
            },
        },
    )
    agg = MetricsAggregator(store)
    metrics = await agg.compute(session_id)
    assert len(metrics.workers) == 1
    assert metrics.workers[0].status == "halted"
    assert metrics.workers[0].worker_id == "w1"
    halted_labels = [p.label for p in metrics.timeline if p.event_type == "worker.halted"]
    assert any("halted" in (lbl or "").lower() for lbl in halted_labels)
    await store.close()
