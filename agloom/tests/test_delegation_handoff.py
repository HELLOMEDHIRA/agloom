"""End-to-end delegation: classifier handoff and explicit ``adelegate``."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from agloom.delegation import HandoffTarget, run_delegate
from agloom.models import ExecutionResult, PatternType, QueryAnalysis
from agloom.unified_agent import create_agent


class _StubChatModel:
    async def ainvoke(self, messages, config=None, **kwargs):
        return AIMessage(content="primary-llm")

    def invoke(self, messages, config=None, **kwargs):
        return AIMessage(content="primary-llm")


def _react_analysis_with_delegate(name: str) -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=3,
        reasoning=f"Route this task to the {name} specialist.",
        subtasks=[],
    )


def _delegate_result(output: str, *, name: str = "coder") -> ExecutionResult:
    return ExecutionResult(
        pattern_used=PatternType.DIRECT,
        query="delegated",
        output=output,
        steps_taken=1,
        success=True,
        metadata={"delegated_to": name},
    )


@pytest.mark.asyncio
async def test_ainvoke_handoff_when_classifier_names_delegate() -> None:
    """``run_fresh`` delegates before pattern dispatch when reasoning mentions a handoff target."""
    delegate_out = "handled-by-coder-delegate"

    class _DelegateAgent:
        name = "coder"

        async def ainvoke(self, query: str, **kwargs: object) -> ExecutionResult:
            return _delegate_result(delegate_out, name="coder")

    with patch(
        "agloom.unified_agent.analyze_query",
        new=AsyncMock(return_value=_react_analysis_with_delegate("coder")),
    ):
        primary = await create_agent(model=_StubChatModel(), name="primary", query_cache=False)
        primary.register_handoff(_DelegateAgent(), name="coder", description="Code specialist")
        try:
            result = await primary.ainvoke("implement feature X", thread_id="handoff-t1")
            assert result.success is True
            assert result.output == delegate_out
            assert result.metadata.get("delegated_to") == "coder"
        finally:
            await primary.aclose()


@pytest.mark.asyncio
async def test_ainvoke_handoff_applies_input_transform() -> None:
    captured_query: list[str] = []

    class _DelegateAgent:
        name = "coder"

        async def ainvoke(self, query: str, **kwargs: object) -> ExecutionResult:
            captured_query.append(query)
            return _delegate_result("ok", name="coder")

    async def prepend_ctx(q: str) -> str:
        return f"CTX:{q}"

    with patch(
        "agloom.unified_agent.analyze_query",
        new=AsyncMock(return_value=_react_analysis_with_delegate("coder")),
    ):
        primary = await create_agent(model=_StubChatModel(), name="primary", query_cache=False)
        primary.register_handoff(
            _DelegateAgent(),
            name="coder",
            description="Code",
            input_transform=prepend_ctx,
        )
        try:
            await primary.ainvoke("fix bug", thread_id="handoff-t2")
            assert captured_query == ["CTX:fix bug"]
        finally:
            await primary.aclose()


@pytest.mark.asyncio
async def test_adelegate_resolves_named_target() -> None:
    calls: list[str] = []

    class _DelegateAgent:
        name = "researcher"

        async def ainvoke(self, query: str, **kwargs: object) -> ExecutionResult:
            calls.append(query)
            return _delegate_result("research-done", name="researcher")

    primary = await create_agent(model=_StubChatModel(), name="primary", query_cache=False)
    primary.register_handoff(_DelegateAgent(), name="researcher", description="Research")
    try:
        result = await primary.adelegate("summarize papers", delegate_name="researcher")
        assert result.output == "research-done"
        assert calls == ["summarize papers"]
    finally:
        await primary.aclose()


@pytest.mark.asyncio
async def test_run_delegate_records_target_name() -> None:
    class _DelegateAgent:
        name = "coder"

        async def ainvoke(self, query: str, **kwargs: object) -> ExecutionResult:
            return ExecutionResult(
                pattern_used=PatternType.DIRECT,
                query=query,
                output=f"echo:{query}",
                success=True,
            )

    target = HandoffTarget(_DelegateAgent(), name="coder", description="test")
    result = await run_delegate(target, "hello", thread_id="td1")
    assert result.output == "echo:hello"
    assert result.success is True


@pytest.mark.asyncio
async def test_handoff_skipped_when_delegate_not_in_reasoning() -> None:
    """No handoff when classifier reasoning does not name a registered delegate."""

    class _DelegateAgent:
        name = "coder"

        async def ainvoke(self, query: str, **kwargs: object) -> ExecutionResult:
            raise AssertionError("delegate should not be invoked")

    analysis = QueryAnalysis(
        pattern=PatternType.DIRECT,
        complexity=1,
        reasoning="Answer directly without delegation.",
        direct_response="direct-only",
        subtasks=[],
    )

    with patch("agloom.unified_agent.analyze_query", new=AsyncMock(return_value=analysis)):
        primary = await create_agent(model=_StubChatModel(), name="primary", query_cache=False)
        primary.register_handoff(_DelegateAgent(), name="coder", description="Code")
        try:
            result = await primary.ainvoke("2+2?", thread_id="handoff-t3")
            assert result.output == "direct-only"
            assert "delegated_to" not in result.metadata
        finally:
            await primary.aclose()
