"""SqliteEventStore streaming replay and batch commits."""

from __future__ import annotations

import pytest

from agloom.protocol.store import SqliteEventStore


@pytest.mark.asyncio
async def test_sqlite_streaming_replay_pages() -> None:
    store = SqliteEventStore(":memory:")
    for i in range(1, 301):
        await store.append("s_stream", {"seq": i, "type": "token.delta"})
    replayed = [e async for e in store.replay("s_stream", from_seq=50)]
    assert len(replayed) == 251
    assert replayed[0]["seq"] == 50
    store.close()


@pytest.mark.asyncio
async def test_sqlite_batch_commits_flush() -> None:
    store = SqliteEventStore(":memory:", batch_commits=True, batch_commit_size=100)
    for i in range(1, 6):
        await store.append("s_batch", {"seq": i, "type": "t"})
    await store.flush()
    replayed = [e async for e in store.replay("s_batch")]
    assert len(replayed) == 5
    store.close()
