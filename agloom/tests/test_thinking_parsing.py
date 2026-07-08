"""Qwen inline thinking tag parsing and enable_thinking configuration."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from agloom.llm.chat_template_compat import patch_strict_template_model_settings
from agloom.patterns.middleware import _prepare_react_model_request
from agloom.src.wire_stream_content import (
    answer_text_from_content,
    sanitize_ai_message_for_history,
    split_stream_parts_from_chunk,
)

# Build tags literally — some editors strip "redacted_" from  markup in source files.
_THINK_OPEN = "<" + "redacted_thinking" + ">"
_THINK_CLOSE = "</" + "redacted_thinking" + ">"


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
