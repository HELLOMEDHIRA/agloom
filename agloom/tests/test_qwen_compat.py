"""Qwen3 / vLLM chat-template compatibility (tool_choice + message flattening)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agloom.llm.qwen_compat import (
    model_needs_qwen_chat_template_compat,
    normalize_messages_for_chat_template,
    resolve_react_tool_choice,
)
from agloom.patterns.middleware import should_force_tool_choice_on_request


def test_model_needs_qwen_compat() -> None:
    assert model_needs_qwen_chat_template_compat("qwen36fp8")
    assert model_needs_qwen_chat_template_compat("litellm/qwen3-30b-a3b")
    assert not model_needs_qwen_chat_template_compat("groq/llama-3.3-70b")


def test_flatten_multimodal_user_blocks() -> None:
    msgs = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "investigate error spike in logs"}],
        }
    ]
    out = normalize_messages_for_chat_template(msgs)
    assert out[0]["content"] == "investigate error spike in logs"


def test_flatten_human_message_object() -> None:
    msgs = [HumanMessage(content=[{"type": "text", "text": "hello"}])]
    out = normalize_messages_for_chat_template(msgs)
    assert isinstance(out[0], HumanMessage)
    assert out[0].content == "hello"


def test_resolve_tool_choice_qwen_opening_uses_auto() -> None:
    msgs = [HumanMessage(content="fetch metrics")]
    assert resolve_react_tool_choice(msgs, model_label="qwen36fp8") == "auto"


def test_resolve_tool_choice_groq_opening_uses_required() -> None:
    msgs = [HumanMessage(content="fetch metrics")]
    assert resolve_react_tool_choice(msgs, model_label="groq/llama-3.3-70b") == "required"


def test_resolve_tool_choice_qwen_multistep_uses_auto() -> None:
    msgs = [
        HumanMessage(content="query logs"),
        AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "1"}]),
        ToolMessage(content="ok", tool_call_id="1"),
    ]
    assert resolve_react_tool_choice(msgs, model_label="qwen36fp8") == "auto"


def test_no_force_after_assistant_prose_recovery() -> None:
    msgs = [
        HumanMessage(content="query"),
        AIMessage(content="Let me check that."),
        HumanMessage(content="Use structured tool calls only."),
    ]
    assert not should_force_tool_choice_on_request(msgs)
