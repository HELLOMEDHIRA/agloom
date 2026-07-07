"""Harness optimistic version conflict detection."""

import pytest

from agloom.harness.progress import HarnessVersionConflictError, ProgressArtifact, ProgressTracker
from langgraph.store.memory import InMemoryStore

from agloom.memory.store import LongTermStore


@pytest.mark.asyncio
async def test_save_progress_raises_on_version_conflict():
    store = LongTermStore(store=InMemoryStore())
    tracker = ProgressTracker(store, "agent", "proj")
    tracker._artifact = ProgressArtifact(project_name="proj", version=2)
    await tracker._lts_save(
        ("harness", "progress"),
        "artifact",
        ProgressArtifact(project_name="proj", version=5).model_dump_json(),
        {},
    )
    with pytest.raises(HarnessVersionConflictError):
        await tracker.save_progress()
