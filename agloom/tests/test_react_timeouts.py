"""REACT wall-clock timeout helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agloom.src.models import AgentEvent, PatternType, QueryAnalysis
from agloom.patterns.react import (
    _handle_react_streaming,
    _react_graph_wall_timeout,
    _react_llm_timeout,
    _react_timeout_failure_message,
)


def _analysis() -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=1,
        reasoning="test",
        subtasks=[],
    )


def test_react_llm_timeout_honors_agent() -> None:
    assert _react_llm_timeout({"llm_timeout": 300}) == 300.0


def test_react_graph_timeout_scales_with_llm() -> None:
    assert _react_graph_wall_timeout({"llm_timeout": 120}) == 480.0
    assert _react_graph_wall_timeout({"llm_timeout": 300}) == 1200.0


def test_react_graph_timeout_explicit_override() -> None:
    assert _react_graph_wall_timeout({"llm_timeout": 120, "react_graph_timeout": 900}) == 900.0


def test_timeout_message_actionable() -> None:
    msg = _react_timeout_failure_message({"llm_timeout": 120}, wall_seconds=480, path="stream")
    assert "llm_timeout" in msg
    assert "react_graph_timeout" in msg


@pytest.mark.asyncio
async def test_stream_timeout_emits_error_event() -> None:
    queue: asyncio.Queue[AgentEvent] = asyncio.Queue()

    async def _astream_events(*_a: object, **_k: object):
        await asyncio.sleep(60)
        yield {"event": "noop"}  # pragma: no cover

    mock_react = MagicMock()
    mock_react.astream_events = _astream_events

    agent = {
        "llm": MagicMock(),
        "tools": [],
        "system_prompt": "sys",
        "name": "Test",
        "react_graph_timeout": 0.05,
        "llm_timeout": 30,
    }

    with (
        patch("agloom.patterns.react.create_agent", return_value=mock_react),
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
    error_evt = await queue.get()
    assert error_evt.type == "error"
    assert error_evt.data.get("error_class") == "TimeoutError"
    assert "timed out" in str(error_evt.data.get("error", "")).lower()
