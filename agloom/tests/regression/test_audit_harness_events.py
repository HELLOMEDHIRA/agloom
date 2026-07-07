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


def test_translator_emits_harness_task_updated_wire():
    import io

    from agloom.protocol import SessionEmitter
    from agloom.runtime.translator import translate
    from agloom.src.models import AgentEvent

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
