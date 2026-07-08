"""Reproduction: the ainvoke tool-loop must SHRINK the request before retrying a
transient transport disconnect ('server disconnected' / RemoteProtocolError).

Current code re-sends the identical oversized state up to _MAX_TRANSPORT_RETRIES
times (react.py:860-873 does `continue` with the same `state`), so an oversized-body
disconnect fails N times identically. After the fix, each transport retry compacts
the state first — mirroring the streaming compact-then-retry path.

FAILS on current code (retry sees the same token count); PASSES once compact-on-retry
is added to `_run_react_ainvoke_with_retries`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agloom.context.tokens import estimate_messages_tokens
from agloom.context.tool_scratchpad import ToolScratchpad
from agloom.patterns.react import _run_react_ainvoke_with_retries
from agloom.src.models import PatternType, QueryAnalysis


def _analysis() -> QueryAnalysis:
    return QueryAnalysis(pattern=PatternType.REACT, complexity=1, reasoning="test", subtasks=[])


@pytest.mark.asyncio
async def test_ainvoke_transport_retry_compacts_before_resending() -> None:
    pad = ToolScratchpad()
    huge = "z" * 60_000
    initial_state = {
        "messages": [
            HumanMessage(content="investigate latency"),
            ToolMessage(content=huge, tool_call_id="tc1", name="observability_get_logs"),
            ToolMessage(content=huge, tool_call_id="tc2", name="observability_get_logs"),
        ]
    }

    seen_tokens: list[int] = []
    attempts = 0

    async def _ainvoke(state, config=None):
        nonlocal attempts
        attempts += 1
        seen_tokens.append(estimate_messages_tokens(list(state.get("messages") or [])))
        if attempts == 1:
            raise RuntimeError("Server disconnected without sending a response")
        return {"messages": list(state.get("messages") or []) + [AIMessage(content="ok, recovered")]}

    react_agent = MagicMock()
    react_agent.ainvoke = AsyncMock(side_effect=_ainvoke)

    tool = MagicMock()
    tool.name = "observability_get_logs"
    # Small window so the ~30k-token request is genuinely oversized (est >= 0.85 * input
    # budget) — this is the "oversized → still compacts" branch of the latency-vs-size gate.
    agent = {
        "llm": MagicMock(),
        "tools": [tool],
        "system_prompt": "sys",
        "name": "ainvoke-compact-retry-test",
        "_tool_scratchpad": pad,
        "context_window_tokens": 32_000,
        "context_reserved_output_tokens": 8192,
        "context_compact_ratio": 0.82,
    }

    with patch(
        "agloom.orchestrator.hooks.maybe_recover_react_failure",
        AsyncMock(side_effect=lambda _a, _c, _q, _an, result: result),
    ):
        result = await _run_react_ainvoke_with_retries(
            agent,
            "investigate latency",
            _analysis(),
            config={"_steps": []},
            react_agent=react_agent,
            initial_state=initial_state,
        )

    assert attempts == 2, "expected exactly one transport retry"
    assert result.success is True
    assert seen_tokens[1] < seen_tokens[0], (
        f"retry re-sent an equal-or-larger body ({seen_tokens[1]} >= {seen_tokens[0]}); "
        "agloom did not compact before retrying"
    )
