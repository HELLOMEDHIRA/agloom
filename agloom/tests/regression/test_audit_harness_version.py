"""Harness optimistic version conflict detection."""

import asyncio

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


@pytest.mark.asyncio
async def test_concurrent_save_progress_serializes_under_lock():
    store = LongTermStore(store=InMemoryStore())
    tracker = ProgressTracker(store, "agent", "proj")
    tracker._artifact = ProgressArtifact(project_name="proj", version=1)

    async def _save() -> int:
        await tracker.save_progress()
        return tracker.artifact.version or 0

    versions = await asyncio.gather(*[_save() for _ in range(8)])
    assert len(set(versions)) == len(versions)
    assert (tracker.artifact.version or 0) == 1 + len(versions)
