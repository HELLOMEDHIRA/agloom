"""Harness ergonomics: seed API and tools appendix."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.store.memory import InMemoryStore

from agloom.harness.metadata import HARNESS_TOOLS_APPENDIX, HarnessMetadata
from agloom.harness.seed import seed_harness_tasks
from agloom.src.unified_agent import _HARNESS_EMPTY_DETAIL, create_agent


@pytest.mark.asyncio
async def test_seed_harness_tasks_idempotent() -> None:
    tracker = MagicMock()
    tracker.artifact = MagicMock()
    tracker.artifact.tasks = [MagicMock()]
    tracker.artifact.description = ""
    tracker.bootstrap = AsyncMock()
    tracker.add_task = AsyncMock()
    tracker.save_progress = AsyncMock()

    with patch("agloom.harness.seed.get_progress_tracker", AsyncMock(return_value=tracker)):
        n = await seed_harness_tasks(
            MagicMock(),
            "agent",
            "proj",
            [{"id": "t1", "description": "do thing"}],
        )
    assert n == 1
    tracker.add_task.assert_not_called()


@pytest.mark.asyncio
async def test_create_agent_appends_harness_appendix() -> None:
    agent = await create_agent(
        model=MagicMock(),
        store=InMemoryStore(),
        harness=True,
        harness_metadata=HarnessMetadata(
            project_name="demo",
            goal="Demo goal",
            init_git=False,
        ),
        name="harness-demo",
    )
    sp = agent.config["system_prompt"]
    assert HARNESS_TOOLS_APPENDIX.strip() in sp
    assert "turn planner" in sp.lower()


def test_harness_empty_detail_documents_turn_planner_triage() -> None:
    assert "turn planner" in _HARNESS_EMPTY_DETAIL
