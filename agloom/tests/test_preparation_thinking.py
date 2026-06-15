"""Wire-visible progress during pre-REACT setup."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agloom.models import AgentEvent
from agloom.runtime.translator import translate
from agloom.tests.test_runtime_bridge import capture_emitter
from agloom.unified_agent import (
    _emit_preparation_progress,
    _ensure_harness_bootstrapped,
)


@pytest.mark.asyncio
async def test_emit_preparation_progress_queues_event() -> None:
    q: asyncio.Queue = asyncio.Queue()
    await _emit_preparation_progress(q, name="analyze_query", detail="Classifying query…")
    evt = await q.get()
    assert evt.type == "progress"
    assert evt.data["phase"] == "classify"
    assert evt.data["name"] == "analyze_query"
    assert "Classifying" in evt.data["output"]


@pytest.mark.asyncio
async def test_harness_bootstrap_emits_progress_when_tasks_exist() -> None:
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
    assert len(events) == 1
    assert events[0].type == "progress"
    assert events[0].data["phase"] == "harness_init"
    assert events[0].data["name"] == "harness_bootstrap"
    assert "2 task" in events[0].data["output"]


@pytest.mark.asyncio
async def test_harness_bootstrap_silent_when_no_tasks() -> None:
    q: asyncio.Queue = asyncio.Queue()
    artifact = MagicMock()
    artifact.tasks = []
    artifact.completion_ratio = 0.0
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

    assert q.empty()


@pytest.mark.asyncio
async def test_harness_bootstrap_failure_still_emits_progress() -> None:
    q: asyncio.Queue = asyncio.Queue()
    tracker = MagicMock()
    tracker._bootstrapped_for_thread = None
    tracker.bootstrap = AsyncMock(side_effect=RuntimeError("store unavailable"))

    config = {
        "_harness_enabled": True,
        "_progress_tracker": tracker,
        "name": "demo",
    }
    await _ensure_harness_bootstrapped(config, "thread_a", (), "my goal", event_queue=q)

    evt = await q.get()
    assert evt.type == "progress"
    assert evt.data["name"] == "harness_bootstrap"
    assert "skipped" in evt.data["output"].lower()


def test_translate_progress_preparation_reaches_wire() -> None:
    em = capture_emitter()
    translate(
        AgentEvent(
            type="progress",
            data={
                "phase": "harness_init",
                "name": "harness_bootstrap",
                "output": "Harness ready · 2 task(s) · 50% complete",
            },
        ),
        em,
    )
    assert em.calls and em.calls[0][0] == "emit_progress_step"
    assert em.calls[0][1]["phase"] == "harness_init"
    assert em.calls[0][1]["label"] == "harness_bootstrap"
