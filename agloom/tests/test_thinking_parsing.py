"""Provider-agnostic inline reasoning parsing and enable_thinking configuration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from agloom.llm.chat_template_compat import patch_strict_template_model_settings
from agloom.llm.reasoning_control import (
    apply_reasoning_preference,
    label_indicates_reasoning_model,
    reasoning_is_active,
    reasoning_preference_kwargs,
)
from agloom.patterns.middleware import _prepare_react_model_request
from agloom.src.wire_stream_content import (
    answer_text_from_content,
    sanitize_ai_message_for_history,
    split_stream_parts_from_chunk,
)

# Build tags literally — some editors strip "redacted_" from  markup in source files.
_THINK_OPEN = "<" + "redacted_thinking" + ">"
_THINK_CLOSE = "</" + "redacted_thinking" + ">"


@pytest.mark.parametrize("tag", ["think", "thinking", "reason", "reasoning"])
def test_inline_reasoning_tags_split_across_conventions(tag: str) -> None:
    payload = f"<{tag}>weigh options carefully</{tag}>The answer is 42."
    reasoning, answer = split_stream_parts_from_chunk(AIMessageChunk(content=payload))
    assert "weigh options" in reasoning
    assert answer.strip() == "The answer is 42."
    assert "<" not in answer


def test_structured_reasoning_content_still_parses() -> None:
    chunk = SimpleNamespace(
        content="Final answer.",
        additional_kwargs={"reasoning_content": "Step one. Step two."},
    )
    reasoning, answer = split_stream_parts_from_chunk(chunk)
    assert reasoning == "Step one. Step two."
    assert answer == "Final answer."


def test_dangling_unclosed_reasoning_tag_is_reasoning() -> None:
    reasoning, answer = split_stream_parts_from_chunk(
        AIMessageChunk(content="<thinking>still deciding mid-stream")
    )
    assert "still deciding" in reasoning
    assert answer == ""


def test_qwen_inline_think_tags_split_into_reasoning() -> None:
    payload = (
        f"{_THINK_OPEN}weigh options carefully{_THINK_CLOSE}The answer is 42."
    )
    reasoning, answer = split_stream_parts_from_chunk(AIMessageChunk(content=payload))
    assert "weigh options" in reasoning
    assert answer.strip() == "The answer is 42."
    assert _THINK_OPEN not in answer


def test_answer_text_strips_think_block() -> None:
    text = f"{_THINK_OPEN}internal reasoning{_THINK_CLOSE}Final response."
    assert answer_text_from_content(text).strip() == "Final response."
    assert "internal reasoning" not in answer_text_from_content(text)


def test_sanitize_ai_message_strips_thinking_from_history() -> None:
    msg = AIMessage(
        content=f"{_THINK_OPEN}secret plan{_THINK_CLOSE}User-visible answer."
    )
    clean = sanitize_ai_message_for_history(msg)
    assert clean.content == "User-visible answer."


def test_patch_does_not_inject_when_enable_thinking_none() -> None:
    result = patch_strict_template_model_settings(None, enable_thinking=None)
    extra = result.get("extra_body") or {}
    ctk = extra.get("chat_template_kwargs") or {}
    assert "enable_thinking" not in ctk


def test_patch_sets_enable_thinking_when_explicit() -> None:
    enabled = patch_strict_template_model_settings(None, enable_thinking=True)
    assert enabled["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    disabled = patch_strict_template_model_settings(None, enable_thinking=False)
    assert disabled["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_middleware_does_not_inject_enable_thinking_by_default() -> None:
    class _ChatLiteLLM:
        model_name = "litellm_proxy/qwen36fp8"

    req = SimpleNamespace(
        messages=[HumanMessage(content="hi")],
        model=_ChatLiteLLM(),
        model_settings=None,
        tools=[],
        state=None,
    )

    def _override(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(**{**req.__dict__, **kwargs})

    req.override = _override  # type: ignore[attr-defined]
    prepared = _prepare_react_model_request(req, tool_choice_enabled=True, enable_thinking=None)
    assert getattr(prepared, "model_settings", None) is None


# --- Fix 2: provider-agnostic reasoning control -----------------------------------------


def test_reasoning_kwargs_none_writes_nothing() -> None:
    assert reasoning_preference_kwargs(enable=None, model_label="litellm/qwen") == {}
    assert reasoning_preference_kwargs(enable=None, model_label="claude-3-5-sonnet") == {}


def test_reasoning_kwargs_vllm_uses_chat_template_kwargs() -> None:
    kw = reasoning_preference_kwargs(enable=False, model_label="litellm_proxy/qwen36fp8")
    assert kw["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    kw_on = reasoning_preference_kwargs(enable=True, model_label="vllm/qwen")
    assert kw_on["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_reasoning_kwargs_anthropic_uses_thinking() -> None:
    off = reasoning_preference_kwargs(enable=False, model_label="claude-3-7-sonnet")
    assert off["thinking"] == {"type": "disabled"}
    on = reasoning_preference_kwargs(enable=True, model_label="anthropic:claude-3-7")
    assert on["thinking"]["type"] == "enabled"


def test_reasoning_kwargs_google_uses_thinking_budget() -> None:
    off = reasoning_preference_kwargs(enable=False, model_label="gemini-2.5-flash")
    assert off["thinking_budget"] == 0


def test_reasoning_kwargs_groq_uses_reasoning_effort() -> None:
    off = reasoning_preference_kwargs(enable=False, model_label="groq/llama-3.3")
    assert off["reasoning_effort"] == "none"


def test_reasoning_kwargs_openai_o_series_is_noop() -> None:
    assert reasoning_preference_kwargs(enable=False, model_label="openai:o3-mini") == {}


def test_apply_reasoning_preference_binds_llm() -> None:
    captured: dict = {}

    class _Model:
        def bind(self, **kwargs: object) -> str:
            captured.update(kwargs)
            return "bound"

    out = apply_reasoning_preference(_Model(), enable=False, model_label="vllm/qwen")
    assert out == "bound"
    assert captured["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False


def test_apply_reasoning_preference_noop_returns_llm_unchanged() -> None:
    sentinel = object()
    assert apply_reasoning_preference(sentinel, enable=None, model_label="vllm/qwen") is sentinel


# --- Fix 4: reasoning-active detection --------------------------------------------------


@pytest.mark.parametrize(
    "label",
    ["openai:o3-mini", "deepseek-r1", "qwq-32b", "qwen3-thinking", "gemini-2.5-flash-thinking"],
)
def test_label_indicates_reasoning_model_true(label: str) -> None:
    assert label_indicates_reasoning_model(label) is True


@pytest.mark.parametrize("label", ["openai:gpt-4o", "claude-3-5-sonnet", "llama-3.3-70b"])
def test_label_indicates_reasoning_model_false(label: str) -> None:
    assert label_indicates_reasoning_model(label) is False


def test_reasoning_is_active_explicit_enable() -> None:
    assert reasoning_is_active(None, enable_thinking=True, model_label="gpt-4o") is True


def test_reasoning_is_active_off_for_plain_model() -> None:
    assert reasoning_is_active(None, enable_thinking=None, model_label="gpt-4o") is False


def test_reasoning_is_active_llm_param() -> None:
    class _Model:
        reasoning_effort = "high"

    assert reasoning_is_active(_Model(), enable_thinking=None, model_label="gpt-4o") is True


# --- Fix 3: classifier requests reasoning OFF and still parses reasoning-wrapped JSON ---


@pytest.mark.asyncio
async def test_classifier_reasoning_off_and_parses_reasoning_wrapped_json() -> None:
    from agloom.src.classifier import analyze_query

    bind_calls: list[dict] = []

    class _LLM:
        model_name = "litellm_proxy/qwen36fp8"

        def bind(self, **kwargs: object) -> _LLM:
            bind_calls.append(kwargs)
            return self

        def with_structured_output(self, *_a: object, **_k: object):
            raise NotImplementedError("no structured output")

        async def ainvoke(self, _messages: object) -> AIMessage:
            # Reasoning model wraps its chain-of-thought then emits the JSON payload.
            return AIMessage(
                content=(
                    "<reasoning>The user just wants a direct answer.</reasoning>"
                    '{"pattern": "DIRECT", "complexity": "1", "reasoning": "simple",'
                    ' "direct_response": "hello there"}'
                )
            )

    analysis = await analyze_query(
        _LLM(),
        "say hello",
        tools=[],
        classifier_timeout=5.0,
        structured_max_retries=1,
    )

    # Not None / not the fallback: the reasoning-wrapped JSON parsed into DIRECT.
    from agloom.src.models import PatternType

    assert analysis.pattern == PatternType.DIRECT
    assert analysis.direct_response == "hello there"
    # Classifier requested reasoning OFF for its internal call (provider-agnostic knob).
    assert any(
        (kw.get("extra_body") or {}).get("chat_template_kwargs", {}).get("enable_thinking") is False
        for kw in bind_calls
    )


# --- Fix 4: timeout floors for reasoning-active models ----------------------------------


def test_scaled_timeouts_raise_defaults_for_reasoning() -> None:
    from agloom.llm.reasoning_control import scaled_timeouts_for_reasoning

    llm_t, cls_t = scaled_timeouts_for_reasoning(120.0, 60.0)
    assert llm_t == 300.0
    assert cls_t == 120.0


def test_scaled_timeouts_preserve_explicit_overrides() -> None:
    from agloom.llm.reasoning_control import scaled_timeouts_for_reasoning

    llm_t, cls_t = scaled_timeouts_for_reasoning(45.0, 200.0)
    assert llm_t == 45.0
    assert cls_t == 200.0
