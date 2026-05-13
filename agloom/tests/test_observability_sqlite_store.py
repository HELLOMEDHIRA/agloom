"""SQLite observability store: schema, idempotency, flush on close."""

from __future__ import annotations

import pytest

from agloom.observability.store.sqlite import SQLiteObservabilityStore


def _env(session: str, seq: int, typ: str, **data: object) -> dict:
    return {
        "session": session,
        "seq": seq,
        "type": typ,
        "ts": "2026-05-09T00:00:00Z",
        "data": dict(data),
    }


@pytest.mark.asyncio
async def test_sqlite_ingest_idempotent_seq(tmp_path) -> None:
    path = str(tmp_path / "obs.db")
    sid = "sess-1"
    store = await SQLiteObservabilityStore.open(path)
    try:
        await store.ingest(_env(sid, 0, "session.opened"))
        await store.ingest(_env(sid, 1, "message.user"))
        await store.ingest(_env(sid, 1, "message.user"))
        assert await store.get_event_count(sid) == 2
    finally:
        await store.close()

    store2 = await SQLiteObservabilityStore.open(path)
    try:
        assert await store2.get_event_count(sid) == 2
    finally:
        await store2.close()


@pytest.mark.asyncio
async def test_sqlite_close_flushes_pending_ingests(tmp_path) -> None:
    path = str(tmp_path / "obs2.db")
    sid = "sess-flush"
    store = await SQLiteObservabilityStore.open(path)
    await store.ingest(_env(sid, 0, "session.opened"))
    for i in range(1, 12):
        await store.ingest(_env(sid, i, "debug.trace", msg=str(i)))
    await store.close()

    store2 = await SQLiteObservabilityStore.open(path)
    try:
        assert await store2.get_event_count(sid) == 12
    finally:
        await store2.close()
