"""Regression tests for automatic long-context transport recovery in ReAct."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from agloom.context.tool_scratchpad import ToolScratchpad
from agloom.patterns.react import (
    _MAX_TRANSPORT_RETRIES,
    _react_base_input_budget,
    _record_adaptive_input_budget_on_transport,
    _run_react_no_tools_direct,
)
from agloom.patterns.tool_context_middleware import ContextBudgetMiddleware
from agloom.src.models import PatternType, QueryAnalysis


def _analysis() -> QueryAnalysis:
    return QueryAnalysis(pattern=PatternType.REACT, complexity=1, reasoning="test", subtasks=[])


@pytest.mark.asyncio
async def test_no_tools_transport_retry_recovers_after_disconnect() -> None:
    attempts = 0
    llm = MagicMock()
    llm.model_name = "gpt-4"

    async def _ainvoke(_messages, **_kw):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Server disconnected without sending a response")
        return AIMessage(content="recovered without tools")

    llm.ainvoke = AsyncMock(side_effect=_ainvoke)

    agent = {
        "llm": llm,
        "system_prompt": "sys",
        "name": "no-tools-recover",
        "context_window_tokens": 128_000,
        "context_reserved_output_tokens": 8192,
        "context_compact_ratio": 0.82,
    }

    with patch(
        "agloom.orchestrator.hooks.maybe_recover_react_failure",
        AsyncMock(side_effect=lambda _a, _c, _q, _an, result: result),
    ):
        result = await _run_react_no_tools_direct(
            agent,
            "hello",
            _analysis(),
            config={"_steps": []},
            steps=[],
            ml=0,
        )

    assert attempts == 2
    assert result.success is True
    assert "recovered" in (result.output or "").lower()


@pytest.mark.asyncio
async def test_no_tools_transport_exhaustion_returns_transport_failure() -> None:
    llm = MagicMock()
    llm.model_name = "gpt-4"
    llm.ainvoke = AsyncMock(
        side_effect=RuntimeError("Server disconnected without sending a response")
    )

    agent = {
        "llm": llm,
        "system_prompt": "sys",
        "name": "no-tools-fail",
        "context_window_tokens": 128_000,
        "context_reserved_output_tokens": 8192,
        "context_compact_ratio": 0.82,
    }

    with patch(
        "agloom.orchestrator.hooks.maybe_recover_react_failure",
        AsyncMock(side_effect=lambda _a, _c, _q, _an, result: result),
    ):
        result = await _run_react_no_tools_direct(
            agent,
            "hello",
            _analysis(),
            config={"_steps": []},
            steps=[],
            ml=0,
        )

    assert not result.success
    assert result.failure_class == "transport"
    assert result.retryable is True
    assert llm.ainvoke.await_count == _MAX_TRANSPORT_RETRIES + 1


@pytest.mark.asyncio
async def test_adaptive_input_budget_lowers_after_oversized_disconnect() -> None:
    agent: dict = {
        "context_window_tokens": 128_000,
        "context_reserved_output_tokens": 8192,
        "context_compact_ratio": 0.82,
    }
    base = _react_base_input_budget(agent)
    est_at_failure = int(base * 0.9)
    _record_adaptive_input_budget_on_transport(agent, est_at_failure)

    adaptive = agent.get("_adaptive_input_budget")
    assert isinstance(adaptive, int)
    assert adaptive == max(2048, int(est_at_failure * 0.8))
    assert adaptive < base

    pad = ToolScratchpad()
    mw = ContextBudgetMiddleware(
        context_window=128_000,
        reserved_output=8192,
        scratchpad=pad,
        compact_ratio=0.82,
        agent_config=agent,
    )
    assert mw._input_budget() == min(base, adaptive)
