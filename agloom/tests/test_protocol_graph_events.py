"""Tests for graph.* events, session.resumed, and EventStore."""
from __future__ import annotations

import asyncio
import io
import json

import pytest

from agloom.protocol import (
    GraphNodeEnter,
    GraphNodeExit,
    SessionResumed,
)
from agloom.protocol.emitter import SessionEmitter
from agloom.protocol.events import event_adapter
from agloom.protocol.store import MemoryEventStore, SqliteEventStore

# GraphNodeEnter / GraphNodeExit round-trip


def _emitter_with_buf() -> tuple[SessionEmitter, io.StringIO]:
    buf = io.StringIO()
    em = SessionEmitter(session="s_1", thread="t_1", writer=buf)
    return em, buf


def _lines(buf: io.StringIO) -> list[dict]:
    return [json.loads(l) for l in buf.getvalue().splitlines() if l.strip()]


def test_emit_graph_node_enter():
    em, buf = _emitter_with_buf()
    em.open()
    evt = em.emit_graph_node_enter(node="classify", pattern="REACT", input_preview="analyze logs")
    assert isinstance(evt, GraphNodeEnter)
    lines = _lines(buf)
    graph_lines = [l for l in lines if l["type"] == "graph.node.enter"]
    assert len(graph_lines) == 1
    assert graph_lines[0]["data"]["node"] == "classify"
    assert graph_lines[0]["data"]["pattern"] == "REACT"
    assert graph_lines[0]["data"]["input_preview"] == "analyze logs"


def test_emit_graph_node_exit():
    em, buf = _emitter_with_buf()
    em.open()
    evt = em.emit_graph_node_exit(
        node="SUPERVISOR",
        pattern="SUPERVISOR",
        duration_ms=120,
        output_preview="done",
    )
    assert isinstance(evt, GraphNodeExit)
    lines = _lines(buf)
    exit_lines = [l for l in lines if l["type"] == "graph.node.exit"]
    assert exit_lines[0]["data"]["duration_ms"] == 120
    assert exit_lines[0]["data"]["output_preview"] == "done"


def test_graph_node_exit_with_error():
    em, buf = _emitter_with_buf()
    em.open()
    em.emit_graph_node_exit(node="classify", error="timeout")
    lines = _lines(buf)
    exit_lines = [l for l in lines if l["type"] == "graph.node.exit"]
    assert exit_lines[0]["data"]["error"] == "timeout"


def test_graph_events_seq_monotonic():
    em, buf = _emitter_with_buf()
    em.open()
    e1 = em.emit_graph_node_enter(node="classify")
    e2 = em.emit_graph_node_exit(node="classify", duration_ms=50)
    assert e2.seq == e1.seq + 1


def test_graph_event_round_trip_via_adapter():
    em, buf = _emitter_with_buf()
    em.open()
    em.emit_graph_node_enter(node="REACT")
    lines = _lines(buf)
    for raw in lines:
        parsed = event_adapter.validate_python(raw)
        assert parsed.type in ("session.opened", "graph.node.enter")


# session.resumed


def test_resume_emits_session_resumed():
    em, buf = _emitter_with_buf()
    evt = em.resume(resumed_from_thread="t_old")
    assert isinstance(evt, SessionResumed)
    lines = _lines(buf)
    assert any(l["type"] == "session.resumed" for l in lines)
    resumed = next(l for l in lines if l["type"] == "session.resumed")
    assert resumed["data"]["resumed_from_thread"] == "t_old"


def test_resume_idempotent():
    em, buf = _emitter_with_buf()
    e1 = em.resume()
    e2 = em.resume()
    assert e1 is e2
    lines = _lines(buf)
    assert sum(1 for l in lines if l["type"] == "session.resumed") == 1


def test_resume_allows_further_emits():
    em, buf = _emitter_with_buf()
    em.resume(resumed_from_thread="t_x", replayed_from_seq=5)
    em.emit_graph_node_enter(node="classify")
    lines = _lines(buf)
    types = [l["type"] for l in lines]
    assert "session.resumed" in types
    assert "graph.node.enter" in types


def test_resumed_event_round_trip():
    em, buf = _emitter_with_buf()
    em.resume(resumed_from_thread="t_abc", replayed_from_seq=3)
    lines = _lines(buf)
    raw = next(l for l in lines if l["type"] == "session.resumed")
    parsed = event_adapter.validate_python(raw)
    assert isinstance(parsed, SessionResumed)
    assert parsed.data.resumed_from_thread == "t_abc"
    assert parsed.data.replayed_from_seq == 3


# MemoryEventStore


@pytest.mark.asyncio
async def test_memory_store_append_and_replay():
    store = MemoryEventStore()
    events = [{"type": "session.opened", "seq": i} for i in range(5)]
    for evt in events:
        await store.append("s_1", evt)
    replayed = [e async for e in store.replay("s_1")]
    assert len(replayed) == 5
    assert replayed[0]["seq"] == 0


@pytest.mark.asyncio
async def test_memory_store_replay_from_seq():
    store = MemoryEventStore()
    for i in range(10):
        await store.append("s_1", {"seq": i, "type": "t"})
    replayed = [e async for e in store.replay("s_1", from_seq=5)]
    assert all(e["seq"] >= 5 for e in replayed)
    assert len(replayed) == 5


@pytest.mark.asyncio
async def test_memory_store_count_and_clear():
    store = MemoryEventStore()
    for i in range(3):
        await store.append("s_1", {"seq": i})
    assert await store.count("s_1") == 3
    await store.clear("s_1")
    assert await store.count("s_1") == 0


@pytest.mark.asyncio
async def test_memory_store_empty_replay():
    store = MemoryEventStore()
    replayed = [e async for e in store.replay("no_such_session")]
    assert replayed == []


@pytest.mark.asyncio
async def test_memory_store_multiple_sessions():
    store = MemoryEventStore()
    await store.append("s_a", {"seq": 1})
    await store.append("s_b", {"seq": 1})
    a = [e async for e in store.replay("s_a")]
    b = [e async for e in store.replay("s_b")]
    assert len(a) == 1
    assert len(b) == 1


@pytest.mark.asyncio
async def test_memory_store_list_session_ids():
    store = MemoryEventStore()
    assert await store.list_session_ids() == []
    await store.append("z_sess", {"seq": 1})
    await store.append("a_sess", {"seq": 1})
    assert await store.list_session_ids() == ["a_sess", "z_sess"]


# SqliteEventStore


@pytest.mark.asyncio
async def test_sqlite_store_append_and_replay():
    store = SqliteEventStore(":memory:")
    for i in range(4):
        await store.append("s_1", {"seq": i, "type": "token.delta"})
    replayed = [e async for e in store.replay("s_1")]
    assert len(replayed) == 4
    store.close()


@pytest.mark.asyncio
async def test_sqlite_store_replay_from_seq():
    store = SqliteEventStore(":memory:")
    for i in range(6):
        await store.append("s_1", {"seq": i, "type": "t"})
    replayed = [e async for e in store.replay("s_1", from_seq=3)]
    assert all(e["seq"] >= 3 for e in replayed)
    assert len(replayed) == 3
    store.close()


@pytest.mark.asyncio
async def test_sqlite_store_count_and_clear():
    store = SqliteEventStore(":memory:")
    for i in range(5):
        await store.append("s_1", {"seq": i})
    assert await store.count("s_1") == 5
    await store.clear("s_1")
    assert await store.count("s_1") == 0
    store.close()


@pytest.mark.asyncio
async def test_sqlite_store_list_session_ids():
    store = SqliteEventStore(":memory:")
    assert await store.list_session_ids() == []
    await store.append("s_b", {"seq": 1, "type": "x"})
    await store.append("s_a", {"seq": 1, "type": "x"})
    assert await store.list_session_ids() == ["s_a", "s_b"]
    store.close()


@pytest.mark.asyncio
async def test_store_wired_into_emitter():
    """Events emitted via SessionEmitter should be persisted in the store."""
    store = MemoryEventStore()
    buf = io.StringIO()
    em = SessionEmitter(session="s_1", thread="t_1", writer=buf, store=store)
    em.open()
    em.emit_graph_node_enter(node="classify")
    em.close()

    # Give asyncio ensure_future a chance to run
    await asyncio.sleep(0.05)

    count = await store.count("s_1")
    assert count >= 2  # at minimum: session.opened + graph.node.enter
