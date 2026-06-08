"""Wire-visible progress during pre-REACT setup."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agloom.models import AgentEvent
from agloom.runtime.translator import translate
from agloom.tests.test_runtime_bridge import capture_emitter
from agloom.unified_agent import _ensure_harness_bootstrapped, _emit_preparation_thinking


@pytest.mark.asyncio
async def test_emit_preparation_thinking_queues_event() -> None:
    q: asyncio.Queue = asyncio.Queue()
    await _emit_preparation_thinking(q, name="analyze_query", detail="Classifying query…")
    evt = await q.get()
    assert evt.type == "thinking"
    assert evt.data["name"] == "analyze_query"
    assert "Classifying" in evt.data["output"]


@pytest.mark.asyncio
async def test_harness_bootstrap_emits_thinking_events() -> None:
    q: asyncio.Queue = asyncio.Queue()
    artifact = MagicMock()
    artifact.tasks = [MagicMock(), MagicMock()]
    artifact.completion_ratio = 0.5
    tracker = MagicMock()
    tracker._bootstrapped_for_thread = None
    tracker.artifact = artifact
    tracker.bootstrap = AsyncMock(return_value=artifact)

    config = {
        "_harness_enabled": True,
        "_progress_tracker": tracker,
        "name": "demo",
    }
    await _ensure_harness_bootstrapped(config, "thread_a", (), "my goal", event_queue=q)

    events: list[AgentEvent] = []
    while not q.empty():
        events.append(await q.get())
    assert len(events) == 2
    assert events[0].data["name"] == "harness_bootstrap"
    assert "Loading" in events[0].data["output"]
    assert "2 task" in events[1].data["output"]


def test_translate_thinking_preparation_reaches_wire() -> None:
    em = capture_emitter()
    translate(
        AgentEvent(
            type="thinking",
            data={"name": "harness_bootstrap", "output": "Loading harness progress artifact…"},
        ),
        em,
    )
    assert em.calls and em.calls[0][0] == "emit_thinking_step"
    assert em.calls[0][1]["label"] == "harness_bootstrap"
