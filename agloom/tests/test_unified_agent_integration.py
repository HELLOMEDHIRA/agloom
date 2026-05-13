"""Integration smoke tests for ``create_agent`` → ``run_fresh`` / ``UnifiedAgent.ainvoke``.

LLM and classifier are mocked so CI does not call real providers. Covers:
  * DIRECT short-circuit (classifier emits ``direct_response``)
  * Pattern handler dispatch via registry override (REACT → stub handler)
  * Session memory persistence after ``ainvoke``
  * ``create_agent_sync`` + synchronous ``invoke`` when no event loop is running
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from agloom.models import ExecutionResult, PatternType, QueryAnalysis
from agloom.unified_agent import UnifiedAgent, create_agent, create_agent_sync


class _StubChatModel:
    """Minimal stand-in for ``BaseChatModel`` (``create_agent`` / ``AgentConfig`` validation)."""

    async def ainvoke(self, messages, config=None, **kwargs):
        return AIMessage(content="stub-llm-reply")

    def invoke(self, messages, config=None, **kwargs):
        return AIMessage(content="stub-llm-reply")


def _analysis_direct_shortcircuit(direct_text: str) -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.DIRECT,
        complexity=1,
        reasoning="integration-stub",
        direct_response=direct_text,
        subtasks=[],
    )


def _analysis_react() -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=2,
        reasoning="integration-stub-react",
        direct_response=None,
        subtasks=[],
    )


@pytest.fixture
def stub_llm():
    return _StubChatModel()


@pytest.mark.asyncio
async def test_ainvoke_direct_shortcircuit_patched_classifier(stub_llm) -> None:
    """Classifier returns DIRECT + ``direct_response`` → no pattern handler / main LLM call."""
    want = "Answer from classifier direct_response."
    with patch("agloom.unified_agent.analyze_query", new=AsyncMock(return_value=_analysis_direct_shortcircuit(want))):
        agent = await create_agent(
            model=stub_llm,
            name="integration-direct",
            query_cache=False,
            auto_summarize=False,
        )
        try:
            result = await agent.ainvoke("What is 2+2?", thread_id="thread-int-1")
            assert result.success is True
            assert result.output == want
            assert result.pattern_used == PatternType.DIRECT
            assert result.run_id != ""
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_ainvoke_routes_to_registry_stub_handler(stub_llm) -> None:
    """``run_fresh`` invokes ``registry[pattern]`` — swap REACT for a lightweight stub."""

    async def stub_react_handler(agent: dict, query: str, analysis: QueryAnalysis, invoke_config: dict):
        assert "thread_id" in invoke_config.get("configurable", {})
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output="handled-by-stub-react",
            steps_taken=1,
            success=True,
            analysis=analysis,
            steps=list(invoke_config.get("_steps") or []),
        )

    with patch("agloom.unified_agent.analyze_query", new=AsyncMock(return_value=_analysis_react())):
        agent = await create_agent(
            model=stub_llm,
            name="integration-react",
            query_cache=False,
            auto_summarize=False,
        )
        reg = dict(agent.config["registry"])
        reg[PatternType.REACT] = stub_react_handler
        agent.config["registry"] = reg
        try:
            result = await agent.ainvoke("run tools please", thread_id="thread-int-2")
            assert result.success is True
            assert result.output == "handled-by-stub-react"
            assert result.pattern_used == PatternType.REACT
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_ainvoke_records_session_memory(stub_llm) -> None:
    """``_record_turn`` should append via ``SessionMemory.aadd_turn`` after a successful run."""
    want = "memorized-output"
    tid = "thread-memory-1"
    with patch("agloom.unified_agent.analyze_query", new=AsyncMock(return_value=_analysis_direct_shortcircuit(want))):
        agent = await create_agent(
            model=stub_llm,
            name="integration-memory",
            query_cache=False,
            auto_summarize=False,
        )
        try:
            await agent.ainvoke("remember this", thread_id=tid)
            mem = agent.config.get("memory")
            assert mem is not None
            ctx = await mem.aformat_context(tid, last_n=5)
            assert "remember this" in ctx
            assert want in ctx
        finally:
            await agent.aclose()


def test_create_agent_sync_and_invoke_without_running_loop(stub_llm) -> None:
    """``create_agent_sync`` + ``invoke`` use nested ``asyncio.run`` when pytest has no loop."""
    want = "sync-path-output"
    with patch("agloom.unified_agent.analyze_query", new=AsyncMock(return_value=_analysis_direct_shortcircuit(want))):
        agent = create_agent_sync(
            model=stub_llm,
            name="integration-sync",
            query_cache=False,
            auto_summarize=False,
        )
        assert isinstance(agent, UnifiedAgent)
        try:
            result = agent.invoke("sync hello", thread_id="thread-sync-1")
            assert result.output == want
            assert result.success is True
        finally:
            asyncio.run(agent.aclose())
