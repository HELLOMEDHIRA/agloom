"""Stream→ainvoke handoff must share the tool_use_failed retry budget."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agloom.models import PatternType, QueryAnalysis, StepType, _make_step
from agloom.patterns.react import (
    _MAX_TOOL_RETRIES,
    _emit_react_tool_steps_to_event_queue,
    _run_react_ainvoke_with_retries,
)


def _analysis() -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=1,
        reasoning="test",
        subtasks=[],
    )


@pytest.mark.asyncio
async def test_attempt_offset_reduces_remaining_retries() -> None:
    """One stream attempt consumed → at most ``_MAX_TOOL_RETRIES - 1`` further ainvokes."""
    calls = 0
    mock_agent = MagicMock()

    async def _ainvoke(*_a: object, **_k: object) -> dict:
        nonlocal calls
        calls += 1
        raise RuntimeError("tool_use_failed")

    mock_agent.ainvoke = AsyncMock(side_effect=_ainvoke)

    agent = {
        "llm": MagicMock(),
        "tools": [MagicMock(name="read_file")],
        "system_prompt": "sys",
        "name": "Test",
    }

    result = await _run_react_ainvoke_with_retries(
        agent,
        "hi",
        _analysis(),
        config={"_steps": []},
        react_agent=mock_agent,
        attempt_offset=1,
        log_prefix="[test]",
    )

    assert not result.success
    assert calls == _MAX_TOOL_RETRIES - 1
    assert result.steps_taken == _MAX_TOOL_RETRIES


@pytest.mark.asyncio
async def test_collect_tool_steps_false_preserves_stream_tool_steps() -> None:
    steps = [
        _make_step(StepType.TOOL_CALL, "read_file", input="{}", id="1"),
        _make_step(StepType.TOOL_RESULT, "read_file", output="ok", id="1"),
    ]
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(return_value={"messages": []})

    agent = {
        "llm": MagicMock(),
        "tools": [],
        "system_prompt": "sys",
        "name": "Test",
    }

    with (
        patch("agloom.patterns.react._extract_last_ai_message", return_value="done"),
        patch("agloom.patterns.react._extract_token_usage", return_value={}),
        patch("agloom.patterns.react._collect_tool_steps") as collect_mock,
    ):
        result = await _run_react_ainvoke_with_retries(
            agent,
            "hi",
            _analysis(),
            config={"_steps": steps},
            react_agent=mock_agent,
            collect_tool_steps=False,
        )

    collect_mock.assert_not_called()
    tool_steps = [s for s in result.steps if s.type in (StepType.TOOL_CALL, StepType.TOOL_RESULT)]
    assert len(tool_steps) == 2


@pytest.mark.asyncio
async def test_emit_tool_steps_skips_wire_emitted_but_emits_new_results() -> None:
    import asyncio

    from agloom.models import AgentEvent

    queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
    agent = {"_event_queue": queue}
    steps = [
        _make_step(StepType.TOOL_CALL, "read_file", input="{}", id="1", wire_emitted=True),
        _make_step(StepType.TOOL_RESULT, "read_file", output="from-stream", id="1", wire_emitted=True),
        _make_step(StepType.TOOL_RESULT, "read_file", output="from-ainvoke", id="1"),
    ]
    await _emit_react_tool_steps_to_event_queue(agent, steps)
    assert queue.empty() is False
    evt = await queue.get()
    assert evt.type == "tool_result"
    assert evt.data.get("output") == "from-ainvoke"
    assert queue.empty()
