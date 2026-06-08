"""EventStore rename validation, append guards, and replay ordering."""

from __future__ import annotations

import asyncio
import io

import pytest

from agloom.protocol.emitter import SessionEmitter
from agloom.protocol.store import MemoryEventStore, SqliteEventStore


@pytest.mark.asyncio
async def test_memory_rename_rejects_invalid_ids() -> None:
    store = MemoryEventStore()
    await store.append("ok", {"seq": 1, "type": "t"})
    with pytest.raises(ValueError, match="invalid session_id"):
        await store.rename_session("", "new")
    with pytest.raises(ValueError, match="invalid session_id"):
        await store.rename_session("ok", "   ")
    replayed = [e async for e in store.replay("ok")]
    assert len(replayed) == 1


@pytest.mark.asyncio
async def test_memory_rename_noop_same_id() -> None:
    store = MemoryEventStore()
    await store.append("s", {"seq": 1, "type": "t"})
    await store.rename_session("s", "s")
    assert await store.count("s") == 1


@pytest.mark.asyncio
async def test_memory_rename_merges_and_sorts_by_seq() -> None:
    store = MemoryEventStore()
    await store.append("old", {"seq": 2, "type": "b"})
    await store.append("old", {"seq": 1, "type": "a"})
    await store.rename_session("old", "new")
    replayed = [e async for e in store.replay("new")]
    assert [e["seq"] for e in replayed] == [1, 2]
    assert await store.count("old") == 0


@pytest.mark.asyncio
async def test_memory_replay_sorted_despite_out_of_order_append() -> None:
    store = MemoryEventStore()
    await store.append("s", {"seq": 3, "type": "c"})
    await store.append("s", {"seq": 1, "type": "a"})
    await store.append("s", {"seq": 2, "type": "b"})
    replayed = [e async for e in store.replay("s")]
    assert [e["seq"] for e in replayed] == [1, 2, 3]


@pytest.mark.asyncio
async def test_memory_append_rejects_bad_seq() -> None:
    store = MemoryEventStore()
    with pytest.raises(ValueError, match="invalid seq"):
        await store.append("s", {"seq": 0, "type": "t"})
    with pytest.raises(ValueError, match="invalid type"):
        await store.append("s", {"seq": 1, "type": ""})


@pytest.mark.asyncio
async def test_sqlite_rename_rejects_invalid_ids() -> None:
    store = SqliteEventStore(":memory:")
    await store.append("ok", {"seq": 1, "type": "t"})
    with pytest.raises(ValueError, match="invalid session_id"):
        await store.rename_session("ok", "")
    store.close()


@pytest.mark.asyncio
async def test_concurrent_memory_appends_all_visible() -> None:
    store = MemoryEventStore()

    async def _append(seq: int) -> None:
        await store.append("s", {"seq": seq, "type": "t"})

    await asyncio.gather(*[_append(i) for i in range(1, 51)])
    assert await store.count("s") == 50
    replayed = [e async for e in store.replay("s")]
    assert len(replayed) == 50
    assert sorted(e["seq"] for e in replayed) == list(range(1, 51))


@pytest.mark.asyncio
async def test_emitter_drain_store_appends_persists_before_assert() -> None:
    store = MemoryEventStore()
    buf = io.StringIO()
    em = SessionEmitter(session="s_drain", thread="t", writer=buf, store=store)
    em.open()
    em.emit_graph_node_enter(node="n")
    em.close()
    await em.drain_store_appends()
    assert await store.count("s_drain") >= 2
