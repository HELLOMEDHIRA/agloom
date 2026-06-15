"""ReactUserTurnToolChoiceMiddleware — opening user turn only (Qwen3-safe)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agloom.patterns.middleware import should_force_tool_choice_on_request


def test_force_on_opening_human_turn() -> None:
    assert should_force_tool_choice_on_request([HumanMessage(content="investigate logs")])
    assert should_force_tool_choice_on_request([{"role": "user", "content": "hi"}])


def test_no_force_after_tool_results_even_with_trailing_human() -> None:
    msgs = [
        HumanMessage(content="query logs"),
        AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "1"}]),
        ToolMessage(content="ok", tool_call_id="1"),
        HumanMessage(content="Use structured tool calls only."),
    ]
    assert not should_force_tool_choice_on_request(msgs)


def test_no_force_when_last_is_tool_message() -> None:
    msgs = [
        HumanMessage(content="query"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
        ToolMessage(content="data", tool_call_id="1"),
    ]
    assert not should_force_tool_choice_on_request(msgs)


def test_force_only_single_user_message() -> None:
    assert should_force_tool_choice_on_request([HumanMessage(content="only turn")])
    assert not should_force_tool_choice_on_request(
        [HumanMessage(content="a"), HumanMessage(content="b")]
    )
