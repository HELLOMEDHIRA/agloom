"""L4 signal listener — asyncio.wait(FIRST_COMPLETED) and HALT_ALL handling."""

from __future__ import annotations

import asyncio

import pytest

from agloom.models import Signal, SignalType
from agloom.patterns.hitl import _listen_for_halt, _should_interrupt


@pytest.mark.asyncio
async def test_listen_for_halt_cancels_workers_on_halt_all() -> None:
    signal_queue: asyncio.Queue = asyncio.Queue()
    halt_event = asyncio.Event()
    agent = {"name": "t", "signal_queue": signal_queue}

    async def _slow() -> str:
        await asyncio.sleep(30)
        return "done"

    t1 = asyncio.create_task(_slow())
    t2 = asyncio.create_task(_slow())
    listener = asyncio.create_task(
        _listen_for_halt(agent=agent, tasks=[t1, t2], halt_event=halt_event)
    )

    await signal_queue.put(Signal(signal_type=SignalType.HALT_ALL, worker_id="w", message="stop"))

    await asyncio.wait_for(listener, timeout=2.0)
    assert halt_event.is_set()
    assert t1.cancelled() or t1.done()
    assert t2.cancelled() or t2.done()
    t1.cancel()
    t2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t1
    with pytest.raises(asyncio.CancelledError):
        await t2


@pytest.mark.asyncio
async def test_listen_for_halt_exits_when_workers_finish_without_signals() -> None:
    signal_queue: asyncio.Queue = asyncio.Queue()
    halt_event = asyncio.Event()
    agent = {"name": "t", "signal_queue": signal_queue}

    async def _fast() -> int:
        return 1

    tasks = [asyncio.create_task(_fast()) for _ in range(3)]
    await asyncio.gather(*tasks)

    await asyncio.wait_for(
        _listen_for_halt(agent=agent, tasks=tasks, halt_event=halt_event),
        timeout=2.0,
    )


def test_should_interrupt_wildcards() -> None:
    assert _should_interrupt("any", ["*"])
    assert _should_interrupt("any", ["__all__"])
    assert _should_interrupt("deployer", ["deployer"])
    assert not _should_interrupt("deployer", ["workers"])
    assert _should_interrupt("workers", ["workers"])
