"""Harness turn planning: needs_plan, derive, sync, execution context."""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from agloom.harness.metadata import HarnessMetadata, bind_harness_project
from agloom.harness.planning import (
    build_harness_execution_context,
    harness_plan_from_subtasks,
    merge_harness_plan_from_subtasks,
    needs_harness_plan,
    sync_harness_from_analysis,
)
from agloom.memory.store import LongTermStore
from agloom.src.classifier import coerce_analysis_when_tools_required
from agloom.src.models import HarnessPlanTask, PatternType, QueryAnalysis, SubTask


@pytest.mark.parametrize(
    "query,expected",
    [
        ("hi", False),
        ("", False),
        ("please investigate checkout latency spike in prod", True),
        ("short q", False),
    ],
)
def test_needs_harness_plan_heuristics(query: str, expected: bool) -> None:
    assert needs_harness_plan(None, harness_enabled=True, user_query=query) is expected


@pytest.mark.asyncio
async def test_needs_harness_plan_false_when_tasks_exist() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj")
    await bind_harness_project(
        tracker,
        HarnessMetadata(
            project_name="proj",
            goal="Goal",
            tasks=[{"id": "t1", "description": "existing"}],
        ),
        session_id="s1",
    )
    assert needs_harness_plan(tracker, harness_enabled=True, user_query="investigate outage") is False


def test_harness_plan_from_subtasks_maps_worker_ids() -> None:
    subtasks = [
        SubTask(worker_id="w1", task="Gather logs"),
        SubTask(worker_id="w2", task="Hypothesis"),
    ]
    plan = harness_plan_from_subtasks(subtasks)
    assert len(plan) == 2
    assert plan[0].task_id == "w1"
    assert plan[0].priority == "critical"
    assert plan[1].task_id == "w2"


def test_merge_harness_plan_from_subtasks_fills_when_empty() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.SUPERVISOR,
        complexity=6,
        reasoning="multi",
        subtasks=[SubTask(worker_id="a", task="Step A")],
    )
    merged = merge_harness_plan_from_subtasks(analysis)
    assert len(merged.harness_plan) == 1
    assert merged.harness_plan[0].task_id == "a"


def test_coerce_to_react_preserves_harness_plan() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.DIRECT,
        complexity=2,
        reasoning="x",
        harness_work_kind="investigation",
        harness_plan=[
            HarnessPlanTask(
                task_id="ctx-1",
                description="Collect timeline",
                category="context",
                priority="high",
                verification_steps=["done"],
            )
        ],
    )
    coerced = coerce_analysis_when_tools_required(
        analysis,
        "fetch error logs from loki last 1h",
        has_tools=True,
    )
    assert coerced.pattern == PatternType.REACT
    assert coerced.harness_work_kind == "investigation"
    assert len(coerced.harness_plan) == 1
    assert coerced.harness_plan[0].task_id == "ctx-1"


@pytest.mark.asyncio
async def test_sync_allow_replan_appends_tasks() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj-replan")
    await bind_harness_project(
        tracker,
        HarnessMetadata(
            project_name="proj-replan",
            goal="Goal",
            tasks=[{"id": "existing", "description": "First"}],
        ),
        session_id="s1",
    )
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=4,
        reasoning="new scope",
        harness_plan=[
            HarnessPlanTask(
                task_id="new-task",
                description="Added later",
                category="planned",
                priority="medium",
                verification_steps=["verified"],
            )
        ],
    )
    assert await sync_harness_from_analysis(tracker, analysis, allow_replan=False) == 0
    n = await sync_harness_from_analysis(tracker, analysis, allow_replan=True)
    assert n == 1
    assert {t.id for t in tracker.artifact.tasks} == {"existing", "new-task"}


@pytest.mark.asyncio
async def test_build_harness_execution_context_shows_active_task() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj-exec")
    await bind_harness_project(
        tracker,
        HarnessMetadata(project_name="proj-exec", goal="Investigate"),
        session_id="s1",
    )
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=4,
        reasoning="rca",
        harness_work_kind="investigation",
        harness_plan=[
            HarnessPlanTask(
                task_id="step-1",
                description="Collect logs",
                category="evidence",
                priority="critical",
                verification_steps=["Logs saved"],
            )
        ],
    )
    await sync_harness_from_analysis(tracker, analysis)
    ctx = build_harness_execution_context(tracker)
    assert "HARNESS CURRENT FOCUS" in ctx
    assert "step-1" in ctx
    assert "investigation" in ctx
