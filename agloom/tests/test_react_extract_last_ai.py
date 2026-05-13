"""``_extract_last_ai_message`` — multimodal content and tool-call skips."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from agloom.patterns.react import _extract_last_ai_message


def test_extract_last_ai_skips_tool_call_messages() -> None:
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "x", "id": "1", "args": {}}]),
        AIMessage(content="Final answer."),
    ]
    assert _extract_last_ai_message({"messages": msgs}) == "Final answer."


def test_extract_last_ai_multimodal_text_blocks() -> None:
    msgs = [
        HumanMessage(content="hi"),
        AIMessage(content=[{"type": "text", "text": "  Hello  "}]),
    ]
    assert _extract_last_ai_message({"messages": msgs}) == "Hello"


def test_extract_last_ai_empty_messages() -> None:
    assert _extract_last_ai_message({}) == ""
    assert _extract_last_ai_message({"messages": []}) == ""
    assert _extract_last_ai_message(None) == ""


def test_extract_last_ai_dict_ai_message_shape() -> None:
    """LangChain / checkpoint dict messages (type ``ai``) should behave like AIMessage."""
    msgs = [
        {"type": "ai", "content": "", "tool_calls": [{"name": "t", "id": "1", "args": {}}]},
        {"type": "ai", "content": "Done."},
    ]
    assert _extract_last_ai_message({"messages": msgs}) == "Done."


def test_extract_last_ai_nested_data_payload() -> None:
    msgs = [
        {
            "type": "ai",
            "data": {
                "content": [{"type": "text", "text": "nested"}],
                "tool_calls": [],
            },
        },
    ]
    assert _extract_last_ai_message({"messages": msgs}) == "nested"


def test_extract_last_ai_content_plus_tool_calls_same_message() -> None:
    """Preamble text before tool_calls must not be discarded."""
    msgs = [
        HumanMessage(content="hi"),
        AIMessage(
            content="I'll look that up.",
            tool_calls=[{"name": "search", "id": "call_1", "args": {}}],
        ),
    ]
    assert _extract_last_ai_message({"messages": msgs}) == "I'll look that up."


def test_extract_last_ai_skips_tool_only_then_uses_prior_text() -> None:
    msgs = [
        AIMessage(content="The answer is 42."),
        AIMessage(content="", tool_calls=[{"name": "t", "id": "1", "args": {}}]),
    ]
    assert _extract_last_ai_message({"messages": msgs}) == "The answer is 42."
