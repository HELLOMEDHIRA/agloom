"""REACT GraphRecursionError must fail like timeouts — not success with mid-conversation text."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.errors import GraphRecursionError

from agloom.src.models import AgentEvent, PatternType, QueryAnalysis
from agloom.patterns.react import (
    REACT_RECURSION_LIMIT,
    _handle_react_streaming,
    _react_recursion_limit,
    _react_recursion_limit_failure_message,
    _run_react_ainvoke_with_retries,
)


def _analysis() -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=1,
        reasoning="test",
        subtasks=[],
    )


def test_recursion_limit_message_stable() -> None:
    msg = _react_recursion_limit_failure_message(limit=25, path="stream")
    assert "25" in msg
    assert "step limit" in msg.lower()
    assert "react_recursion_limit" in msg


def test_react_recursion_limit_from_agent() -> None:
    assert _react_recursion_limit({}) == REACT_RECURSION_LIMIT
    assert _react_recursion_limit({"react_recursion_limit": 40}) == 40
    assert _react_recursion_limit({"react_recursion_limit": 0}) == 1
    assert _react_recursion_limit({"react_recursion_limit": 9999}) == 500


@pytest.mark.asyncio
async def test_ainvoke_recursion_limit_honors_agent_override() -> None:
    mock_agent = MagicMock()
    captured: dict[str, int] = {}

    async def _ainvoke(_state: object, *, config: object, **_k: object) -> dict:
        _ = _state
        if isinstance(config, dict):
            captured["limit"] = int(config.get("recursion_limit", 0))
        raise GraphRecursionError("limit")

    mock_agent.ainvoke = AsyncMock(side_effect=_ainvoke)

    agent = {
        "llm": MagicMock(),
        "tools": [],
        "system_prompt": "sys",
        "name": "Test",
        "react_recursion_limit": 40,
    }

    with patch(
        "agloom.orchestrator.hooks.maybe_recover_react_failure",
        AsyncMock(side_effect=lambda _a, _c, _q, _an, result: result),
    ):
        result = await _run_react_ainvoke_with_retries(
            agent,
            "task",
            _analysis(),
            config={"_steps": []},
            react_agent=mock_agent,
        )

    assert captured["limit"] == 40
    assert not result.success
    assert result.steps_taken == 40
    assert "40" in result.output


@pytest.mark.asyncio
async def test_ainvoke_recursion_limit_is_failure_not_last_ai_message() -> None:
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(side_effect=GraphRecursionError("limit"))

    agent = {
        "llm": MagicMock(),
        "tools": [],
        "system_prompt": "sys",
        "name": "Test",
    }

    with patch("agloom.patterns.react._extract_last_ai_message", return_value="What would you like me to do?"):
        result = await _run_react_ainvoke_with_retries(
            agent,
            "investigate outage",
            _analysis(),
            config={"_steps": []},
            react_agent=mock_agent,
            log_prefix="[React]",
        )

    assert not result.success
    assert result.steps_taken == REACT_RECURSION_LIMIT
    assert "What would you like" not in result.output
    assert result.error
    assert "step limit" in result.error.lower()


@pytest.mark.asyncio
async def test_stream_recursion_limit_emits_error_event() -> None:
    queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

    async def _astream_events(*_a: object, **_k: object):
        raise GraphRecursionError("limit")
        yield  # pragma: no cover — makes this an async generator

    mock_react = MagicMock()
    mock_react.astream_events = _astream_events

    agent = {
        "llm": MagicMock(),
        "tools": [],
        "system_prompt": "sys",
        "name": "Test",
        "react_graph_timeout": 60,
        "llm_timeout": 30,
    }

    with (
        patch("agloom.patterns.react.create_agent", return_value=mock_react),
        patch("agloom.patterns.react._extract_last_ai_message", return_value="partial garbage"),
        patch(
            "agloom.orchestrator.hooks.maybe_recover_react_failure",
            AsyncMock(side_effect=lambda _a, _c, _q, _an, result: result),
        ),
    ):
        result = await _handle_react_streaming(
            agent,
            "query",
            _analysis(),
            config={"_steps": []},
            event_queue=queue,
        )

    assert not result.success
    assert "partial garbage" not in result.output

    error_evt = await queue.get()
    assert error_evt.type == "error"
    assert error_evt.data.get("error_class") == "GraphRecursionError"
    assert "step limit" in str(error_evt.data.get("error", "")).lower()
