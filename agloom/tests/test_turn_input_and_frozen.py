"""Phase 1 (messages input) and Phase 2 (frozen execution plan) verification."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agloom.frozen import clear_frozen_plan, frozen_replay_active, get_frozen_plan
from agloom.models import PatternType, QueryAnalysis
from agloom.turn_input import normalize_turn_input
from agloom.unified_agent import _HANDLERS, create_agent


class _StubChatModel:
    async def ainvoke(self, messages, config=None, **kwargs):
        return AIMessage(content="stub-out")

    def invoke(self, messages, config=None, **kwargs):
        return AIMessage(content="stub-out")

    async def astream(self, messages, config=None, **kwargs):
        yield AIMessage(content="streamed")


def _direct_analysis(text: str = "direct-out") -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.DIRECT,
        complexity=1,
        reasoning="test",
        direct_response=text,
        subtasks=[],
    )


# --- Phase 1: turn input ---


def test_normalize_messages_dict() -> None:
    turn = normalize_turn_input(
        {"messages": [{"role": "user", "content": "Hello from LangChain"}]}
    )
    assert turn.user_text == "Hello from LangChain"
    assert turn.wire_snapshot == "Hello from LangChain"


def test_normalize_human_message_object() -> None:
    turn = normalize_turn_input({"messages": [HumanMessage("Hi")]})
    assert turn.user_text == "Hi"


def test_normalize_string_sugar() -> None:
    turn = normalize_turn_input("plain")
    assert turn.user_text == "plain"


def test_reject_non_messages_dict() -> None:
    with pytest.raises(ValueError, match="messages"):
        normalize_turn_input({"text": "nope"})


# --- Phase 2: frozen true/false ---


@pytest.mark.asyncio
async def test_frozen_false_classifies_every_turn() -> None:
    classify_mock = AsyncMock(return_value=_direct_analysis())
    agent = await create_agent(model=_StubChatModel(), name="dyn", query_cache=False, frozen=False)
    inp = {"messages": [{"role": "user", "content": "one"}]}
    with patch("agloom.unified_agent.analyze_query", classify_mock):
        try:
            await agent.ainvoke(inp, thread_id="dyn-1")
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": "two"}]},
                thread_id="dyn-2",
            )
            assert classify_mock.await_count == 2
            assert get_frozen_plan(agent.config) is None
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_frozen_true_classifies_once_replays_second() -> None:
    classify_mock = AsyncMock(return_value=_direct_analysis())
    agent = await create_agent(
        model=_StubChatModel(),
        name="frz",
        query_cache=False,
        frozen=True,
        system_prompt="Translate to French.",
    )
    with patch("agloom.unified_agent.analyze_query", classify_mock):
        try:
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": "Hello"}]},
                thread_id="frz-1",
            )
            assert classify_mock.await_count == 1
            assert get_frozen_plan(agent.config) is not None
            assert frozen_replay_active(agent.config)

            classify_mock.reset_mock()
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": "Bonjour"}]},
                thread_id="frz-2",
            )
            classify_mock.assert_not_called()
            plan = get_frozen_plan(agent.config)
            assert plan is not None
            assert plan.analysis.pattern == PatternType.DIRECT
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_frozen_string_sugar_same_as_messages() -> None:
    classify_mock = AsyncMock(return_value=_direct_analysis())
    agent = await create_agent(model=_StubChatModel(), name="frz-str", query_cache=False, frozen=True)
    with patch("agloom.unified_agent.analyze_query", classify_mock):
        try:
            await agent.ainvoke("first", thread_id="fs-1")
            classify_mock.reset_mock()
            await agent.ainvoke("second", thread_id="fs-2")
            classify_mock.assert_not_called()
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_frozen_astream_events_same_plan() -> None:
    classify_mock = AsyncMock(return_value=_direct_analysis())
    agent = await create_agent(model=_StubChatModel(), name="frz-ev", query_cache=False, frozen=True)
    with patch("agloom.unified_agent.analyze_query", classify_mock):
        try:
            async for _ in agent.astream_events(
                {"messages": [{"role": "user", "content": "a"}]},
                thread_id="fe-1",
            ):
                pass
            assert classify_mock.await_count == 1
            classify_mock.reset_mock()
            async for _ in agent.astream_events(
                {"messages": [{"role": "user", "content": "b"}]},
                thread_id="fe-2",
            ):
                pass
            classify_mock.assert_not_called()
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_reset_frozen_reclassifies() -> None:
    classify_mock = AsyncMock(return_value=_direct_analysis())
    agent = await create_agent(model=_StubChatModel(), name="frz-rst", query_cache=False, frozen=True)
    with patch("agloom.unified_agent.analyze_query", classify_mock):
        try:
            await agent.ainvoke({"messages": [{"role": "user", "content": "x"}]}, thread_id="rst-1")
            agent.reset_frozen()
            classify_mock.reset_mock()
            await agent.ainvoke({"messages": [{"role": "user", "content": "y"}]}, thread_id="rst-2")
            assert classify_mock.await_count == 1
        finally:
            await agent.aclose()


@pytest.mark.asyncio
async def test_frozen_prelocked_skips_classify() -> None:
    classify_mock = AsyncMock(side_effect=AssertionError("classify"))
    agent = await create_agent(model=_StubChatModel(), name="frz-pre", query_cache=False, frozen=True)
    analysis = _direct_analysis()
    agent.config["frozen_analysis"] = analysis
    agent.config["_frozen_handler"] = _HANDLERS[PatternType.DIRECT]
    from agloom.frozen import build_execution_plan

    build_execution_plan(
        agent.config,
        analysis=analysis,
        handler=_HANDLERS[PatternType.DIRECT],
        classify_text="locked",
        execution_mode="handler",
    )
    with patch("agloom.unified_agent.analyze_query", classify_mock):
        try:
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "anything"}]},
                thread_id="pre-1",
            )
            assert result.success
            classify_mock.assert_not_called()
        finally:
            await agent.aclose()
