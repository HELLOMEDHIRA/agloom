"""Qwen3 / vLLM / LiteLLM chat-template compatibility (tool_choice + message flattening)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agloom.llm.qwen_compat import (
    _ChatTemplateCompatProxy,
    ensure_messages_for_chat_template,
    extract_model_label,
    model_needs_qwen_chat_template_compat,
    normalize_messages_for_chat_template,
    repair_messages_for_chat_template,
    resolve_react_tool_choice,
    tag_llm_for_chat_template_compat,
    wrap_chat_model_for_react_compat,
)
from agloom.patterns.middleware import should_force_tool_choice_on_request


def test_model_needs_qwen_compat() -> None:
    assert model_needs_qwen_chat_template_compat("qwen36fp8")
    assert model_needs_qwen_chat_template_compat("litellm:qwen3-30b-a3b")
    assert model_needs_qwen_chat_template_compat("litellm hosted_vllm/default")
    assert not model_needs_qwen_chat_template_compat("groq/llama-3.3-70b")
    assert not model_needs_qwen_chat_template_compat("litellm:groq/llama-3.3-70b")


def test_litellm_class_triggers_compat() -> None:
    class ChatLiteLLM:
        model = "corporate-alias-v1"

    assert model_needs_qwen_chat_template_compat(extract_model_label(ChatLiteLLM()))


def test_tagged_model_label_used() -> None:
    class M:
        model = "corporate-alias-v1"

    m = M()
    tag_llm_for_chat_template_compat(m, "litellm:qwen36fp8")
    assert model_needs_qwen_chat_template_compat(extract_model_label(m))


def test_flatten_multimodal_user_blocks() -> None:
    msgs = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "investigate error spike in logs"}],
        }
    ]
    out = normalize_messages_for_chat_template(msgs)
    assert out[0]["content"] == "investigate error spike in logs"


def test_repair_user_from_state_when_request_empty() -> None:
    state = {"messages": [HumanMessage(content="real investigation query")]}
    out = repair_messages_for_chat_template([], state=state)
    assert len(out) == 1
    assert out[0].content == "real investigation query"


def test_resolve_tool_choice_qwen_never_forces() -> None:
    msgs = [HumanMessage(content="fetch metrics")]
    assert resolve_react_tool_choice(msgs, model_label="qwen36fp8") is None


def test_resolve_tool_choice_groq_opening_uses_required() -> None:
    msgs = [HumanMessage(content="fetch metrics")]
    assert resolve_react_tool_choice(msgs, model_label="groq/llama-3.3-70b") == "required"


def test_resolve_tool_choice_litellm_opaque_never_forces() -> None:
    msgs = [HumanMessage(content="fetch metrics")]
    assert resolve_react_tool_choice(msgs, model_label="litellm corporate-alias") is None


def test_resolve_tool_choice_qwen_multistep_never_forces() -> None:
    msgs = [
        HumanMessage(content="query logs"),
        AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "1"}]),
        ToolMessage(content="ok", tool_call_id="1"),
    ]
    assert resolve_react_tool_choice(msgs, model_label="qwen36fp8") is None


def test_no_force_after_assistant_prose_recovery() -> None:
    msgs = [
        HumanMessage(content="query"),
        AIMessage(content="Let me check that."),
        HumanMessage(content="Use structured tool calls only."),
    ]
    assert not should_force_tool_choice_on_request(msgs)


def test_ensure_messages_fills_empty_user() -> None:
    out = ensure_messages_for_chat_template([HumanMessage(content="")])
    assert out[0].content
    assert "tools" in str(out[0].content).lower()


def test_proxy_repairs_messages_on_ainvoke() -> None:
    captured: list[Any] = []

    class FakeLLM:
        model = "alias"

        async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> str:
            captured.append(list(input))
            return "ok"

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            return self

    wrapped = wrap_chat_model_for_react_compat(FakeLLM(), "litellm:qwen36fp8")
    assert isinstance(wrapped, _ChatTemplateCompatProxy)

    import asyncio

    asyncio.run(wrapped.ainvoke([HumanMessage(content="")]))
    assert captured
    assert captured[0][0].content


def test_proxy_strips_tool_choice_on_bind_tools() -> None:
    seen: dict[str, Any] = {}

    class FakeLLM:
        model = "alias"

        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
            seen.update(kwargs)
            return self

    wrapped = wrap_chat_model_for_react_compat(FakeLLM(), "litellm:qwen36fp8")
    wrapped.bind_tools([], tool_choice="required")
    assert "tool_choice" not in seen
