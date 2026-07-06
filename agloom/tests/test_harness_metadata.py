"""Harness metadata contract and lifecycle."""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore
from unittest.mock import AsyncMock, MagicMock

from agloom.harness.metadata import (
    HarnessMetadata,
    bind_harness_project,
    format_harness_metadata_for_classifier,
    validate_harness_create_agent_kwargs,
)
from agloom.harness.planning import sync_harness_from_analysis
from agloom.memory.store import LongTermStore
from agloom.src.models import HarnessPlanTask, PatternType, QueryAnalysis, SubTask
from agloom.src.unified_agent import _HARNESS_EMPTY_DETAIL, create_agent


def test_validate_harness_requires_metadata() -> None:
    with pytest.raises(ValueError, match="harness_metadata"):
        validate_harness_create_agent_kwargs(
            harness=True,
            harness_metadata=None,
            store=object(),
            harness_available=True,
        )


def test_validate_harness_metadata_forbidden_when_off() -> None:
    with pytest.raises(ValueError, match="harness=True"):
        validate_harness_create_agent_kwargs(
            harness=False,
            harness_metadata={"project_name": "p", "goal": "g"},
            store=object(),
            harness_available=True,
        )


def test_format_harness_metadata_for_classifier() -> None:
    text = format_harness_metadata_for_classifier(
        HarnessMetadata(project_name="rca-1", goal="Find root cause", init_git=False),
        needs_plan=True,
    )
    assert "HARNESS PROJECT" in text
    assert "rca-1" in text
    assert "harness_plan" in text
    assert "allow_replan" in text
    assert "force_plan" in text


@pytest.mark.asyncio
async def test_bind_harness_project_sets_goal_and_tasks() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj-a")
    meta = HarnessMetadata(
        project_name="proj-a",
        goal="Fix checkout latency",
        init_git=False,
        tasks=[{"id": "ctx-1", "description": "Collect timeline"}],
    )
    await bind_harness_project(tracker, meta, session_id="s1")
    assert tracker.artifact.description == "Fix checkout latency"
    assert len(tracker.artifact.tasks) == 1
    assert tracker.artifact.tasks[0].id == "ctx-1"


@pytest.mark.asyncio
async def test_sync_harness_from_analysis_seeds_subtasks() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj-b")
    await bind_harness_project(
        tracker,
        HarnessMetadata(project_name="proj-b", goal="Investigate outage"),
        session_id="s1",
    )
    analysis = QueryAnalysis(
        pattern=PatternType.SUPERVISOR,
        complexity=6,
        reasoning="multi-step",
        subtasks=[
            SubTask(worker_id="w1", task="Gather logs"),
            SubTask(worker_id="w2", task="Form hypothesis"),
        ],
    )
    n = await sync_harness_from_analysis(tracker, analysis)
    assert n == 2
    assert tracker.artifact.work_kind == "SUPERVISOR"
    assert {t.id for t in tracker.artifact.tasks} == {"w1", "w2"}


@pytest.mark.asyncio
async def test_sync_harness_from_harness_plan_on_react() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj-d")
    await bind_harness_project(
        tracker,
        HarnessMetadata(project_name="proj-d", goal="Investigate outage"),
        session_id="s1",
    )
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=4,
        reasoning="tooling rca",
        subtasks=[],
        harness_work_kind="investigation",
        harness_plan=[
            HarnessPlanTask(
                task_id="ctx-1",
                description="Collect alert timeline",
                category="context",
                priority="critical",
                verification_steps=["Timeline has UTC timestamps"],
            ),
        ],
    )
    n = await sync_harness_from_analysis(tracker, analysis)
    assert n == 1
    assert tracker.artifact.work_kind == "investigation"
    assert tracker.artifact.tasks[0].id == "ctx-1"


@pytest.mark.asyncio
async def test_sync_harness_skips_when_tasks_exist() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj-c")
    await bind_harness_project(
        tracker,
        HarnessMetadata(
            project_name="proj-c",
            goal="Goal",
            tasks=[{"id": "existing", "description": "already"}],
        ),
        session_id="s1",
    )
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=3,
        reasoning="x",
        subtasks=[SubTask(worker_id="new", task="ignored")],
    )
    assert await sync_harness_from_analysis(tracker, analysis) == 0


@pytest.mark.asyncio
async def test_create_agent_harness_requires_metadata() -> None:
    llm = MagicMock()
    store = InMemoryStore()
    with pytest.raises(ValueError, match="harness_metadata"):
        await create_agent(model=llm, store=store, harness=True, name="x")


@pytest.mark.asyncio
async def test_create_agent_harness_with_metadata() -> None:
    llm = MagicMock()
    store = InMemoryStore()
    agent = await create_agent(
        model=llm,
        store=store,
        harness=True,
        name="harness-meta",
        harness_metadata=HarnessMetadata(
            project_name="rca-1",
            goal="Database spike",
            init_git=False,
        ),
    )
    assert agent.config["_harness_enabled"] is True
    assert agent.config["_harness_metadata"].project_name == "rca-1"


def test_harness_empty_detail_mentions_turn_planner() -> None:
    assert "turn planner" in _HARNESS_EMPTY_DETAIL
