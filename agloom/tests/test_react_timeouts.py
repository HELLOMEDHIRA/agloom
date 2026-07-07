"""REACT wall-clock timeout helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agloom.context.tool_scratchpad import ToolScratchpad
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


@pytest.mark.asyncio
async def test_stream_transport_compact_retry_after_compaction() -> None:
    """First stream fails with transient transport; compacted retry succeeds (strict, no ainvoke)."""
    pad = ToolScratchpad()
    huge = "z" * 60_000
    initial_state = {
        "messages": [
            HumanMessage(content="investigate latency"),
            ToolMessage(content=huge, tool_call_id="tc1", name="observability_get_logs"),
            ToolMessage(content=huge, tool_call_id="tc2", name="observability_get_logs"),
        ]
    }
    stream_attempts = 0

    async def _astream_events(state: dict, **_k: object):
        nonlocal stream_attempts
        stream_attempts += 1
        if stream_attempts == 1:
            raise RuntimeError("Server disconnected without sending a response")
        yield {
            "event": "on_chain_end",
            "data": {
                "output": {
                    "messages": list(state.get("messages") or [])
                    + [AIMessage(content="Recovered after stream compact retry.")]
                }
            },
        }

    mock_react = MagicMock()
    mock_react.astream_events = _astream_events

    agent = {
        "llm": MagicMock(),
        "tools": [MagicMock(name="observability_get_logs")],
        "system_prompt": "sys",
        "name": "compact-retry-test",
        "strict_execution": True,
        "_tool_scratchpad": pad,
        "context_window_tokens": 128_000,
        "context_reserved_output_tokens": 8192,
        "context_compact_ratio": 0.82,
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
            "investigate latency",
            _analysis(),
            config={"_steps": []},
            initial_state=initial_state,
            stream_compact_retry_remaining=1,
        )

    assert stream_attempts == 2
    assert result.success is True
    assert "Recovered after stream compact retry" in (result.output or "")
