"""Harness AGP events on task mutation."""

import asyncio

import pytest

from agloom.harness.progress import ProgressTracker, TaskStatus
from agloom.src.models import AgentEvent
from langgraph.store.memory import InMemoryStore

from agloom.memory.store import LongTermStore


@pytest.mark.asyncio
async def test_progress_tracker_emits_task_updated():
    store = LongTermStore(store=InMemoryStore())
    eq: asyncio.Queue = asyncio.Queue()
    tracker = ProgressTracker(store, "agent", "proj", event_queue=eq)
    tracker.artifact.tasks = []
    from agloom.harness.progress import Task, TaskPriority

    task = Task(id="t1", category="test", description="do thing", priority=TaskPriority.MEDIUM)
    tracker.artifact.tasks.append(task)
    await tracker.update_task("t1", status=TaskStatus.IN_PROGRESS, notes="working")
    evt = await asyncio.wait_for(eq.get(), timeout=1.0)
    assert isinstance(evt, AgentEvent)
    assert evt.type == "harness_task_updated"
    assert evt.data["task_id"] == "t1"


@pytest.mark.asyncio
async def test_emit_harness_task_updated_uses_event_queue_when_provided():
    from agloom.observability.harness_events import emit_harness_task_updated

    eq: asyncio.Queue = asyncio.Queue()
    await emit_harness_task_updated(
        task_id="t2",
        status="done",
        notes="ok",
        event_queue=eq,
    )
    evt = await asyncio.wait_for(eq.get(), timeout=1.0)
    assert isinstance(evt, AgentEvent)
    assert evt.type == "harness_task_updated"
    assert evt.data["task_id"] == "t2"


def test_translate_fifo_harness_synced_before_task_updated():
    import io
    import json

    from agloom.protocol import SessionEmitter
    from agloom.runtime.translator import translate

    buf = io.StringIO()
    emitter = SessionEmitter(session="s", thread="t", writer=buf)
    emitter.open()
    translate(
        AgentEvent(
            type="harness.synced",
            data={"action": "skip", "task_count": 1, "completion_ratio": 0.0},
        ),
        emitter,
    )
    translate(
        AgentEvent(
            type="harness_task_updated",
            data={"task_id": "t1", "status": "in_progress", "notes": "n"},
        ),
        emitter,
    )
    lines = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    harness_types = [line["type"] for line in lines if line["type"].startswith("harness.")]
    assert harness_types.index("harness.synced") < harness_types.index("harness.task.updated")


def test_translator_emits_harness_task_updated_wire():
    import io

    from agloom.protocol import SessionEmitter
    from agloom.runtime.translator import translate

    class _Emitter(SessionEmitter):
        def __init__(self) -> None:
            super().__init__(session="s", thread="t", writer=io.StringIO())
            self.calls: list[tuple[str, dict]] = []

        def emit_harness_task_updated(self, **kwargs):  # type: ignore[no-untyped-def]
            self.calls.append(("emit_harness_task_updated", kwargs))
            return super().emit_harness_task_updated(**kwargs)

    emitter = _Emitter()
    translate(
        AgentEvent(
            type="harness_task_updated",
            data={"task_id": "t1", "status": "in_progress", "notes": "n", "project": "p"},
        ),
        emitter,
    )
    assert emitter.calls
    assert emitter.calls[0][0] == "emit_harness_task_updated"
    assert emitter.calls[0][1]["task_id"] == "t1"
