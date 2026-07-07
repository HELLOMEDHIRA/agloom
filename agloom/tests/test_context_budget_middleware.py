"""Pre-flight context budget gate in ContextBudgetMiddleware."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agloom.context.errors import ContextBudgetExceededError
from agloom.context.tool_scratchpad import ToolScratchpad
from agloom.patterns.tool_context_middleware import ContextBudgetMiddleware


class _Req:
    def __init__(self, messages: list) -> None:
        self.messages = messages

    def override(self, *, messages: list) -> _Req:
        return _Req(messages)


@pytest.mark.asyncio
async def test_preflight_gate_raises_when_still_over_budget():
    pad = ToolScratchpad()
    huge = "z" * 200_000
    messages = [
        HumanMessage(content="investigate"),
        AIMessage(content="calling tool"),
        ToolMessage(content=huge, tool_call_id="t1", name="logs"),
        HumanMessage(content="more"),
        AIMessage(content="x" * 50_000),
    ]
    mw = ContextBudgetMiddleware(
        context_window=4096,
        reserved_output=512,
        scratchpad=pad,
        compact_ratio=0.82,
    )
    called = False

    async def handler(request: _Req) -> str:
        nonlocal called
        called = True
        return "ok"

    with pytest.raises(ContextBudgetExceededError) as exc_info:
        await mw.awrap_model_call(_Req(messages), handler)
    assert exc_info.value.estimated_tokens > exc_info.value.budget
    assert not called
