"""Memory command gating while invoke is active."""

from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import AsyncMock

import pytest

from agloom.protocol import SessionEmitter, event_adapter
from agloom.protocol.commands import CommandMemoryClear, CommandMemoryClearData
from agloom.runtime.command_dispatch import dispatch_command
from agloom.runtime.hitl import HITLBridge


def _read_events(buf: io.StringIO) -> list:
    buf.seek(0)
    return [event_adapter.validate_python(json.loads(line)) for line in buf if line.strip()]


@pytest.mark.asyncio
async def test_memory_clear_rejected_while_invoke_running() -> None:
    mem = type("Mem", (), {"aclear_thread": AsyncMock()})()

    class _Agent:
        config = {"memory": mem}

    buf = io.StringIO()
    emitter = SessionEmitter(session="s", thread="t_busy", writer=buf)
    emitter.open()
    bridge = HITLBridge(emitter)

    async def _block() -> None:
        await asyncio.sleep(3600)

    task = asyncio.create_task(_block())
    try:
        await dispatch_command(
            CommandMemoryClear(data=CommandMemoryClearData(thread="t_busy")),
            agent=_Agent(),
            emitter=emitter,
            hitl_bridge=bridge,
            invocation_tasks=set(),
            thread_tasks={"t_busy": task},
            shutdown=asyncio.Event(),
        )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    events = _read_events(buf)
    assert any(
        e.type == "error.transient" and "invoke is running" in getattr(e.data, "message", "")
        for e in events
    )
    mem.aclear_thread.assert_not_called()
