"""Qwen3 / vLLM chat-template compatibility helpers for tool-bearing agents."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from ..multimodal import content_blocks_to_text

_QWEN_MODEL_MARKERS = (
    "qwen",
    "qwq",
)


def extract_model_label(model: Any) -> str:
    """Best-effort model id from a LangChain chat model instance."""
    for attr in ("model_name", "model", "model_id", "model_group"):
        value = getattr(model, attr, None)
        if value:
            return str(value).lower()
    bound = getattr(model, "bound", None)
    if bound is not None and bound is not model:
        nested = extract_model_label(bound)
        if nested:
            return nested
    return ""


def model_needs_qwen_chat_template_compat(model_label: str) -> bool:
    """True for Qwen-family models served via LiteLLM, vLLM, Together, etc."""
    label = (model_label or "").lower()
    return any(marker in label for marker in _QWEN_MODEL_MARKERS)


def _human_content_as_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, list):
        text = content_blocks_to_text(content).strip()
        return text or None
    text = str(content).strip()
    return text or None


def _replace_human_content(msg: Any, text: str) -> Any:
    if isinstance(msg, HumanMessage):
        return HumanMessage(content=text, id=msg.id, name=msg.name)
    if isinstance(msg, dict):
        updated = dict(msg)
        updated["content"] = text
        return updated
    content = text
    try:
        return msg.model_copy(update={"content": content})  # type: ignore[attr-defined]
    except Exception:
        try:
            msg.content = content  # type: ignore[attr-defined]
        except Exception:
            pass
    return msg


def normalize_messages_for_chat_template(messages: list[Any]) -> list[Any]:
    """Flatten multimodal user content blocks to plain strings.

    Qwen3 Jinja chat templates (vLLM / LiteLLM) often fail with
    ``No user query found in messages`` when ``role=user`` content is a
    LangChain content-block list instead of a string.
    """
    if not messages:
        return messages
    out: list[Any] = []
    changed = False
    for msg in messages:
        if not _is_human_message(msg):
            out.append(msg)
            continue
        if isinstance(msg, HumanMessage):
            raw = msg.content
        elif isinstance(msg, dict):
            raw = msg.get("content")
        else:
            raw = getattr(msg, "content", None)
        if isinstance(raw, str):
            out.append(msg)
            continue
        flat = _human_content_as_text(raw)
        if flat is None:
            out.append(msg)
            continue
        out.append(_replace_human_content(msg, flat))
        changed = True
    return out if changed else messages


def _is_human_message(msg: Any) -> bool:
    if isinstance(msg, HumanMessage):
        return True
    if isinstance(msg, dict):
        role = str(msg.get("role") or "").lower()
        return role in ("user", "human")
    role = str(getattr(msg, "type", None) or getattr(msg, "role", None) or "").lower()
    return role in ("human", "user")


def resolve_react_tool_choice(
    messages: list[Any] | None,
    *,
    model_label: str,
) -> str | None:
    """Opening-turn tool choice for ReAct; Qwen3 must use ``auto``, not ``required``."""
    if not messages:
        return None
    opening = len(messages) == 1 and _is_human_message(messages[0])
    qwen = model_needs_qwen_chat_template_compat(model_label)
    if opening:
        return "auto" if qwen else "required"
    if qwen:
        return "auto"
    return None
