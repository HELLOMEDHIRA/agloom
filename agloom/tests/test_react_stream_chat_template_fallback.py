"""Stream→ainvoke fallback repairs message state after chat-template failures."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agloom.patterns.react import _handle_react_streaming
from agloom.src.models import PatternType, QueryAnalysis


def _analysis() -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=1,
        reasoning="test",
        subtasks=[],
    )


@pytest.mark.asyncio
async def test_stream_fallback_repairs_state_after_missing_user_query() -> None:
    inner = RuntimeError("No user query found in messages.")
    stream_exc = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])

    class StreamAgent:
        async def astream_events(self, *_a: object, **_k: object):
            raise stream_exc
            yield  # pragma: no cover

    mock_react = StreamAgent()
    captured_states: list[dict] = []

    async def _ainvoke(state: dict, **_k: object) -> dict:
        captured_states.append(state)
        return {
            "messages": state["messages"]
            + [AIMessage(content="Recovered after template repair.")]
        }

    mock_react.ainvoke = AsyncMock(side_effect=_ainvoke)  # type: ignore[attr-defined]

    agent = {
        "llm": MagicMock(),
        "tools": [MagicMock(name="search_logs")],
        "system_prompt": "sys",
        "name": "rca-test",
        "_event_queue": MagicMock(),
        "llm_timeout": 30.0,
    }

    with (
        patch("agloom.patterns.react.create_agent", return_value=mock_react),
        patch("agloom.patterns.react._extract_last_ai_message", return_value="Recovered after template repair."),
        patch("agloom.patterns.react._extract_token_usage", return_value={}),
        patch("agloom.patterns.react._collect_tool_steps"),
    ):
        result = await _handle_react_streaming(
            agent,
            "investigate checkout latency spike",
            _analysis(),
            config={"_steps": []},
            event_queue=MagicMock(),
        )

    assert result.success
    assert captured_states
    first_human = next(
        m for m in captured_states[0]["messages"] if getattr(m, "type", "") == "human" or m.__class__.__name__ == "HumanMessage"
    )
    assert "checkout" in str(getattr(first_human, "content", ""))


@pytest.mark.asyncio
async def test_stream_fallback_sanitizes_partial_state_without_user() -> None:
    partial_msgs = [
        AIMessage(content="", tool_calls=[{"name": "search_logs", "args": {}, "id": "1"}]),
        ToolMessage(content="log lines", tool_call_id="1"),
    ]

    class StreamAgent:
        async def astream_events(self, state: dict, **_k: object):
            if len(state.get("messages") or []) == 1:
                raise ExceptionGroup(
                    "unhandled errors in a TaskGroup (1 sub-exception)",
                    [ConnectionError("mcp disconnected")],
                )
            yield {"event": "on_chain_end", "data": {"output": {"messages": partial_msgs}}}

    mock_react = StreamAgent()
    captured_states: list[dict] = []

    async def _ainvoke(state: dict, **_k: object) -> dict:
        captured_states.append(state)
        return {"messages": state["messages"] + [AIMessage(content="done")]}

    mock_react.ainvoke = AsyncMock(side_effect=_ainvoke)  # type: ignore[attr-defined]

    agent = {
        "llm": MagicMock(),
        "tools": [MagicMock(name="search_logs")],
        "system_prompt": "sys",
        "name": "rca-test",
        "_event_queue": MagicMock(),
        "llm_timeout": 30.0,
    }

    with (
        patch("agloom.patterns.react.create_agent", return_value=mock_react),
        patch("agloom.patterns.react._extract_last_ai_message", return_value="done"),
        patch("agloom.patterns.react._extract_token_usage", return_value={}),
        patch("agloom.patterns.react._collect_tool_steps"),
    ):
        result = await _handle_react_streaming(
            agent,
            "investigate latency",
            _analysis(),
            config={"_steps": []},
            event_queue=MagicMock(),
        )

    assert result.success
    assert captured_states
    assert any(
        getattr(m, "type", "") == "human" or m.__class__.__name__ == "HumanMessage"
        for m in captured_states[0]["messages"]
    )
