"""ExceptionGroup / TaskGroup unwrapping for actionable error messages."""

from __future__ import annotations

import pytest
from langgraph.errors import GraphRecursionError

from agloom.src.exception_utils import (
    exception_indicates_transient_transport_error,
    format_exception_message,
    unwrap_exception,
)
from agloom.src.models import PatternType, QueryAnalysis
from agloom.patterns.react import _run_react_ainvoke_with_retries


def test_unwrap_exception_group_surfaces_sub_exception() -> None:
    inner = PermissionError("403 Forbidden")
    outer = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])
    assert unwrap_exception(outer) is inner


def test_format_exception_message_unwraps_taskgroup() -> None:
    inner = ConnectionError("MCP server refused connection")
    outer = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])
    msg = format_exception_message(outer)
    assert "TaskGroup" not in msg
    assert "ConnectionError" in msg
    assert "refused connection" in msg


@pytest.mark.asyncio
async def test_react_failure_surfaces_root_cause_not_taskgroup_wrapper() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    inner = RuntimeError("tool read_logs timed out")
    outer = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(side_effect=outer)

    agent = {
        "llm": MagicMock(),
        "tools": [],
        "system_prompt": "sys",
        "name": "Test",
    }
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=1,
        reasoning="test",
        subtasks=[],
    )

    with patch(
        "agloom.orchestrator.hooks.maybe_recover_react_failure",
        AsyncMock(side_effect=lambda _a, _c, _q, _an, result: result),
    ):
        result = await _run_react_ainvoke_with_retries(
            agent,
            "investigate",
            analysis,
            config={"_steps": []},
            react_agent=mock_agent,
        )

    assert not result.success
    assert "TaskGroup" not in (result.output or "")
    assert "read_logs timed out" in (result.output or "")
    assert "read_logs timed out" in (result.error or "")


def test_format_exception_message_plain_exception() -> None:
    assert format_exception_message(ValueError("bad arg")) == "ValueError: bad arg"


def test_format_exception_message_graph_recursion() -> None:
    msg = format_exception_message(GraphRecursionError("limit"))
    assert "GraphRecursionError" in msg


def test_format_exception_message_includes_http_response_body() -> None:
    class FakeResponse:
        status_code = 400
        url = "http://10.10.10.30:4000/chat/completions"
        text = '{"error":{"message":"No user query found in messages","type":"BadRequestError"}}'

    class FakeHTTPError(Exception):
        def __str__(self) -> str:
            return "Client error '400 Bad Request' for url 'http://10.10.10.30:4000/chat/completions'"

    exc = FakeHTTPError()
    exc.response = FakeResponse()  # type: ignore[attr-defined]
    msg = format_exception_message(exc)
    assert "No user query found" in msg
    assert "status=400" in msg


def test_exception_indicates_transient_transport_remote_protocol() -> None:
    class RemoteProtocolError(Exception):
        pass

    err = RemoteProtocolError("Server disconnected without sending a response.")
    assert exception_indicates_transient_transport_error(err)


def test_format_exception_message_transport_hint() -> None:
    err = RuntimeError("Server disconnected without sending a response.")
    msg = format_exception_message(err)
    assert "Transient HTTP transport failure" in msg


@pytest.mark.asyncio
async def test_react_retries_transient_transport_then_succeeds() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from langchain_core.messages import AIMessage

    transport_err = RuntimeError("RemoteProtocolError: Server disconnected without sending a response.")
    ok_response = {"messages": [AIMessage(content="done")]}

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(side_effect=[transport_err, transport_err, ok_response])

    agent = {
        "llm": MagicMock(),
        "tools": [],
        "system_prompt": "sys",
        "name": "Test",
        "llm_timeout": 120.0,
    }
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=1,
        reasoning="test",
        subtasks=[],
    )

    with patch(
        "agloom.orchestrator.hooks.maybe_recover_react_failure",
        AsyncMock(side_effect=lambda _a, _c, _q, _an, result: result),
    ):
        result = await _run_react_ainvoke_with_retries(
            agent,
            "investigate",
            analysis,
            config={"_steps": []},
            react_agent=mock_agent,
        )

    assert result.success
    assert mock_agent.ainvoke.await_count == 3
