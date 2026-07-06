"""Production fixes: Core wire payload, turn-2 classify, workers, replan."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.store.memory import InMemoryStore

from agloom.harness.metadata import HarnessMetadata, bind_harness_project
from agloom.harness.planning import (
    classifier_harness_wire_enabled,
    needs_harness_replan,
    sync_harness_from_analysis,
)
from agloom.memory.store import LongTermStore
from agloom.patterns._resolve import resolve_worker_configs
from agloom.src.models import (
    HarnessPlanTask,
    PatternType,
    QueryAnalysis,
    QueryAnalysisToolPayloadCore,
    SubTask,
    query_analysis_from_tool_payload,
)
from agloom.src.frozen import frozen_replay_active
from agloom.src.unified_agent import _turn_harness_focus, _turn_state, create_agent


class _StubChatModel:
    async def ainvoke(self, messages, config=None, **kwargs):
        return AIMessage(content="stub-out")

    def invoke(self, messages, config=None, **kwargs):
        return AIMessage(content="stub-out")


def test_core_payload_turn2_does_not_crash() -> None:
    raw = QueryAnalysisToolPayloadCore(pattern="REACT", complexity="4", reasoning="continue")
    analysis = query_analysis_from_tool_payload(raw, tools_available=True)
    assert analysis.pattern == PatternType.REACT
    assert analysis.harness_plan == []
    assert analysis.harness_work_kind == ""


@pytest.mark.asyncio
async def test_classifier_wire_disabled_when_ledger_has_tasks() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj")
    await bind_harness_project(
        tracker,
        HarnessMetadata(project_name="proj", goal="Goal", tasks=[{"id": "t1", "description": "x"}]),
        session_id="s1",
    )
    assert (
        classifier_harness_wire_enabled(
            tracker,
            harness_enabled=True,
            user_query="please investigate latency",
            metadata=HarnessMetadata(project_name="proj", goal="Goal"),
        )
        is False
    )


def test_classifier_wire_enabled_for_replan() -> None:
    from unittest.mock import MagicMock

    tracker = MagicMock()
    tracker.artifact.tasks = [MagicMock()]
    meta = HarnessMetadata(project_name="p", goal="g", allow_replan=True)
    assert needs_harness_replan(
        tracker,
        harness_enabled=True,
        user_query="add new tasks for the database migration scope",
        allow_replan=True,
    )
    assert classifier_harness_wire_enabled(
        tracker,
        harness_enabled=True,
        user_query="add new tasks for the database migration scope",
        metadata=meta,
    )


@pytest.mark.asyncio
async def test_sync_turn2_with_core_analysis_works() -> None:
    store = LongTermStore(store=InMemoryStore())
    from agloom.harness.progress import get_progress_tracker

    tracker = await get_progress_tracker(store, "agent", "proj-b")
    await bind_harness_project(
        tracker,
        HarnessMetadata(project_name="proj-b", goal="Investigate"),
        session_id="s1",
    )
    analysis = query_analysis_from_tool_payload(
        QueryAnalysisToolPayloadCore(pattern="REACT", complexity="3", reasoning="next step"),
        tools_available=True,
    )
    assert await sync_harness_from_analysis(tracker, analysis, allow_replan=False) == 0
    assert len(tracker.artifact.tasks) == 0


def test_resolve_worker_inherits_harness_focus() -> None:
    agent = {
        "tools": [],
        "system_prompt": "sys",
        "react_recursion_limit": 5,
        "_harness_execution_context": "=== HARNESS CURRENT FOCUS ===\nactive_task: [w1] Do thing",
    }
    plans = [SubTask(worker_id="w1", task="Run checks")]
    cfgs = resolve_worker_configs(agent, plans)
    assert "HARNESS CURRENT FOCUS" in cfgs[0].task
    assert "Run checks" in cfgs[0].task


@pytest.mark.asyncio
async def test_force_plan_short_query() -> None:
    from agloom.harness.planning import needs_harness_plan

    assert needs_harness_plan(
        None,
        harness_enabled=True,
        user_query="fix CVE-9",
        metadata=HarnessMetadata(project_name="p", goal="g", force_plan=True),
    )


def test_turn_state_isolated_per_invoke_config() -> None:
    ic_a: dict = {}
    ic_b: dict = {}
    _turn_state(ic_a)["_harness_execution_context"] = "focus-a"
    _turn_state(ic_b)["_harness_execution_context"] = "focus-b"
    assert _turn_harness_focus(ic_a) == "focus-a"
    assert _turn_harness_focus(ic_b) == "focus-b"


@pytest.mark.asyncio
async def test_frozen_harness_seeds_ledger_on_lock() -> None:
    react_plan = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=4,
        reasoning="investigation",
        harness_work_kind="investigation",
        harness_plan=[
            HarnessPlanTask(
                task_id="step-1",
                description="Collect logs",
                category="evidence",
                priority="high",
                verification_steps=["done"],
            )
        ],
    )
    with patch("agloom.src.unified_agent.analyze_query", AsyncMock(return_value=react_plan)):
        agent = await create_agent(
            model=_StubChatModel(),
            store=InMemoryStore(),
            harness=True,
            frozen=True,
            name="frozen-harness",
            harness_metadata=HarnessMetadata(
                project_name="fh-proj",
                goal="Investigate outage",
                init_git=False,
            ),
            query_cache=False,
        )
        try:
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": "please investigate checkout latency spike"}]},
                thread_id="fh-1",
            )
            tracker = agent.config.get("_progress_tracker")
            assert tracker is not None
            assert any(t.id == "step-1" for t in tracker.artifact.tasks)
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": "continuing investigation"}]},
                thread_id="fh-1",
            )
            assert frozen_replay_active(agent.config)
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_concurrent_ainvoke_turn_state_does_not_cross() -> None:
    async def fake_analyze(llm, query, tools, skill_context="", **kwargs):
        if "message-a" in query:
            return QueryAnalysis(
                pattern=PatternType.DIRECT,
                complexity=1,
                reasoning="a",
                direct_response="out-a",
            )
        return QueryAnalysis(
            pattern=PatternType.DIRECT,
            complexity=1,
            reasoning="b",
            direct_response="out-b",
        )

    agent = await create_agent(
        model=_StubChatModel(),
        store=InMemoryStore(),
        harness=True,
        name="conc",
        harness_metadata=HarnessMetadata(project_name="c", goal="g", init_git=False),
        query_cache=False,
    )
    try:
        with patch("agloom.src.unified_agent.analyze_query", side_effect=fake_analyze):
            r1, r2 = await asyncio.gather(
                agent.ainvoke("message-a", thread_id="ta"),
                agent.ainvoke("message-b", thread_id="tb"),
            )
        assert {r1.output, r2.output} == {"out-a", "out-b"}
        assert agent.config.get("_run_fresh_lock") is not None
    finally:
        await agent.aclose()
