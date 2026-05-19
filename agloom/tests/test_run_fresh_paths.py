"""Correctness tests for ``run_fresh`` and ``_try_direct_stream`` shared prep paths."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agloom.delegation import HandoffTarget
from agloom.models import ExecutionResult, PatternType, QueryAnalysis
from agloom.unified_agent import (
    _build_classifier_augmented_query,
    _build_skill_context_for_classify,
    _coerce_unknown_pattern_handler,
    _HANDLERS,
    create_agent,
)


class _StubChatModel:
    async def ainvoke(self, messages, config=None, **kwargs):
        return AIMessage(content="stub")

    def invoke(self, messages, config=None, **kwargs):
        return AIMessage(content="stub")

    async def astream(self, messages, config=None, **kwargs):
        yield AIMessage(content="streamed")


def _direct_analysis(text: str = "direct answer") -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.DIRECT,
        complexity=1,
        reasoning="test",
        direct_response=text,
        subtasks=[],
    )


@pytest.mark.asyncio
async def test_coerce_unknown_pattern_to_react() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.BLACKBOARD,
        complexity=5,
        reasoning="want blackboard",
        subtasks=[],
    )
    registry: dict = {PatternType.BLACKBOARD: None}
    out = _coerce_unknown_pattern_handler({"name": "t"}, analysis, registry=registry)
    assert out.pattern == PatternType.REACT
    assert "BLACKBOARD" in (out.reasoning or "")


@pytest.mark.asyncio
async def test_skill_context_includes_delegation_targets() -> None:
    target = HandoffTarget(MagicMock(), name="coder", description="Writes code")

    class _Injector:
        async def get_context(self, query: str) -> str:
            return f"skills:{query}"

    ctx = await _build_skill_context_for_classify(
        {
            "name": "t",
            "skill_injector": _Injector(),
            "_delegate_targets": [target],
        },
        processed_query="fix bug",
    )
    assert "skills:fix bug" in ctx
    assert "coder" in ctx
    assert "AVAILABLE DELEGATES" in ctx


@pytest.mark.asyncio
async def test_try_direct_stream_uses_shared_classifier_prep(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_execute(cfg, *, augmented_query, skill_context):
        captured["augmented_query"] = augmented_query
        captured["skill_context"] = skill_context
        return _direct_analysis()

    monkeypatch.setattr("agloom.unified_agent._execute_analyze_query", fake_execute)
    monkeypatch.setattr("agloom.unified_agent._ensure_mcp_connected", AsyncMock())
    monkeypatch.setattr("agloom.unified_agent._ensure_skills_bootstrapped", AsyncMock())
    monkeypatch.setattr("agloom.unified_agent._ensure_harness_bootstrapped", AsyncMock())
    monkeypatch.setattr(
        "agloom.unified_agent.build_memory_context",
        AsyncMock(return_value="MEM"),
    )

    agent = await create_agent(model=_StubChatModel(), name="stream-prep", query_cache=False)
    try:
        expected_aug = _build_classifier_augmented_query("MEM", "", "hello")
        stream = await agent._try_direct_stream(
            "hello",
            thread_id="t1",
            user_id=None,
            lt_namespace=None,
            context={},
        )
        assert stream is not None
        chunks = [c async for c in stream]
        assert "".join(chunks) == "streamed"
        assert captured["augmented_query"] == expected_aug
        assert captured["skill_context"] == ""
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_run_fresh_coerces_unknown_pattern_via_ainvoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """Classifier returns a pattern with no handler → run_fresh coerces and stub REACT runs."""

    async def stub_react(agent: dict, query: str, analysis: QueryAnalysis, invoke_config: dict):
        return ExecutionResult(
            pattern_used=analysis.pattern,
            query=query,
            output="react-stub",
            steps_taken=1,
            success=True,
            analysis=analysis,
        )

    unknown = QueryAnalysis(
        pattern=PatternType.BLACKBOARD,
        complexity=4,
        reasoning="blackboard please",
        subtasks=[],
    )

    with patch("agloom.unified_agent.analyze_query", new=AsyncMock(return_value=unknown)):
        agent = await create_agent(model=_StubChatModel(), name="coerce-test", query_cache=False)
        reg = {k: v for k, v in agent.config["registry"].items() if k != PatternType.BLACKBOARD}
        reg[PatternType.REACT] = stub_react
        agent.config["registry"] = reg
        try:
            result = await agent.ainvoke("route me", thread_id="coerce-t1")
            assert result.success is True
            assert result.pattern_used == PatternType.REACT
            assert result.output == "react-stub"
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_frozen_agent_skips_live_classify_on_invoke(monkeypatch: pytest.MonkeyPatch) -> None:
    frozen_analysis = _direct_analysis("frozen-out")
    classify_mock = AsyncMock(side_effect=AssertionError("live classify should not run"))

    agent = await create_agent(
        model=_StubChatModel(),
        name="frozen",
        query_cache=False,
        frozen=True,
    )
    from agloom.frozen import build_execution_plan

    agent.config["frozen_analysis"] = frozen_analysis
    agent.config["_frozen_handler"] = _HANDLERS[PatternType.DIRECT]
    build_execution_plan(
        agent.config,
        analysis=frozen_analysis,
        handler=_HANDLERS[PatternType.DIRECT],
        classify_text="anything",
        execution_mode="handler",
    )

    with patch("agloom.unified_agent.analyze_query", classify_mock):
        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "anything"}]},
                thread_id="frozen-t1",
            )
            assert result.output == "frozen-out"
            classify_mock.assert_not_called()
        finally:
            await agent.aclose()
