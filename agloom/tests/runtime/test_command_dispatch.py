"""Integration tests for shared runtime command dispatch."""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from agloom.protocol import SessionEmitter, event_adapter
from agloom.protocol.commands import (
    CommandPing,
    CommandPingData,
    CommandRuntimeShutdown,
    CommandRuntimeShutdownData,
    CommandSessionDelete,
    CommandSessionDeleteData,
    CommandSessionRename,
    CommandSessionRenameData,
)
from agloom.protocol.store import MemoryEventStore
from agloom.runtime.command_dispatch import DispatchResult, dispatch_command
from agloom.runtime.hitl import HITLBridge


def _read_events(buf: io.StringIO) -> list:
    buf.seek(0)
    return [event_adapter.validate_python(json.loads(line)) for line in buf if line.strip()]


@pytest.mark.asyncio
async def test_dispatch_ping_emits_pong() -> None:
    buf = io.StringIO()
    emitter = SessionEmitter(session="s", thread="t", writer=buf)
    emitter.open()
    bridge = HITLBridge(emitter)

    result = await dispatch_command(
        CommandPing(data=CommandPingData(ping_id="p1")),
        agent=object(),
        emitter=emitter,
        hitl_bridge=bridge,
        invocation_tasks=set(),
        thread_tasks={},
        shutdown=asyncio.Event(),
    )

    assert result is DispatchResult.CONTINUE
    types = [e.type for e in _read_events(buf)]
    assert "runtime.pong" in types


@pytest.mark.asyncio
async def test_dispatch_shutdown_sets_flag() -> None:
    buf = io.StringIO()
    emitter = SessionEmitter(session="s", thread="t", writer=buf)
    emitter.open()
    bridge = HITLBridge(emitter)
    shutdown = asyncio.Event()

    result = await dispatch_command(
        CommandRuntimeShutdown(data=CommandRuntimeShutdownData()),
        agent=object(),
        emitter=emitter,
        hitl_bridge=bridge,
        invocation_tasks=set(),
        thread_tasks={},
        shutdown=shutdown,
    )

    assert result is DispatchResult.SHUTDOWN
    assert shutdown.is_set()


@pytest.mark.asyncio
async def test_session_delete_refuses_foreign_session() -> None:
    buf = io.StringIO()
    emitter = SessionEmitter(session="sess_a", thread="t", writer=buf)
    emitter.open()
    store = MemoryEventStore()
    bridge = HITLBridge(emitter)

    await dispatch_command(
        CommandSessionDelete(data=CommandSessionDeleteData(session_id="sess_b")),
        agent=object(),
        emitter=emitter,
        hitl_bridge=bridge,
        invocation_tasks=set(),
        thread_tasks={},
        shutdown=asyncio.Event(),
        store=store,
        session_id="sess_a",
    )

    events = _read_events(buf)
    assert any(e.type == "error.transient" for e in events)


@pytest.mark.asyncio
async def test_session_rename_refuses_foreign_session() -> None:
    buf = io.StringIO()
    emitter = SessionEmitter(session="sess_a", thread="t", writer=buf)
    emitter.open()
    store = MemoryEventStore()
    bridge = HITLBridge(emitter)

    await dispatch_command(
        CommandSessionRename(
            data=CommandSessionRenameData(from_session_id="sess_b", to_session_id="sess_c"),
        ),
        agent=object(),
        emitter=emitter,
        hitl_bridge=bridge,
        invocation_tasks=set(),
        thread_tasks={},
        shutdown=asyncio.Event(),
        store=store,
        session_id="sess_a",
    )

    events = _read_events(buf)
    assert any(e.type == "error.transient" for e in events)
