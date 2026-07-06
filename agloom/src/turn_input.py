"""Normalize LangChain-style invoke input into a per-turn structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .multimodal import content_blocks_to_text, text_from_user_turn

_USER_ROLES = frozenset({"user", "human"})


@dataclass
class TurnInput:
    """Normalized input for one agent turn (LangChain ``messages`` shape)."""

    messages: list[Any] = field(default_factory=list)
    user_text: str = ""
    user_turn: str | list[dict[str, Any]] = ""
    wire_snapshot: str = ""


def _content_from_message(msg: Any) -> str:
    if isinstance(msg, dict):
        role = str(msg.get("role") or msg.get("type") or "").lower()
        if role and role not in _USER_ROLES:
            return ""
        content = msg.get("content")
    else:
        role = str(getattr(msg, "type", None) or getattr(msg, "role", "") or "").lower()
        if role and role not in _USER_ROLES and role not in ("humanmessage",):
            type_name = type(msg).__name__.lower()
            if "human" not in type_name and "user" not in type_name:
                return ""
        content = getattr(msg, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return content_blocks_to_text(content)


def _user_turn_from_message(msg: Any) -> str | list[dict[str, Any]]:
    if isinstance(msg, dict):
        content = msg.get("content")
    else:
        content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    text = content_blocks_to_text(content)
    return text if text else ""


def _latest_user_message(messages: list[Any]) -> Any | None:
    for msg in reversed(messages):
        if isinstance(msg, dict):
            role = str(msg.get("role") or "").lower()
            if role in _USER_ROLES:
                return msg
        else:
            role = str(getattr(msg, "type", None) or getattr(msg, "role", "") or "").lower()
            type_name = type(msg).__name__.lower()
            if role in _USER_ROLES or "human" in type_name:
                return msg
    return None


def normalize_turn_input(value: str | dict[str, Any] | list[Any]) -> TurnInput:
    """Accept LangChain invoke shapes and legacy str / multimodal list."""
    if isinstance(value, str):
        text = value.strip()
        return TurnInput(
            messages=[{"role": "user", "content": value}],
            user_text=text,
            user_turn=value,
            wire_snapshot=text,
        )

    if isinstance(value, list):
        if value and isinstance(value[0], dict) and value[0].get("type") in (
            "text",
            "image",
            "image_url",
            "input_audio",
        ):
            text = text_from_user_turn(value)
            return TurnInput(
                messages=[{"role": "user", "content": value}],
                user_text=text,
                user_turn=value,
                wire_snapshot=text,
            )
        return normalize_turn_input({"messages": value})

    if not isinstance(value, dict):
        raise TypeError(f"Unsupported invoke input type: {type(value)!r}")

    if "messages" in value:
        messages = list(value["messages"] or [])
        if not messages:
            raise ValueError("invoke input 'messages' must be a non-empty list.")
        latest = _latest_user_message(messages)
        if latest is None:
            raise ValueError(
                "invoke input 'messages' must include at least one user/human message."
            )
        user_text = _content_from_message(latest).strip()
        if not user_text and isinstance(latest, dict):
            blocks = latest.get("content")
            if isinstance(blocks, list):
                user_text = text_from_user_turn(blocks).strip()
        if not user_text:
            raise ValueError("Latest user message has no text content.")
        user_turn = _user_turn_from_message(latest)
        return TurnInput(
            messages=messages,
            user_text=user_text,
            user_turn=user_turn,
            wire_snapshot=user_text,
        )

    raise ValueError(
        'Invoke input must be {"messages": [...]} (LangChain create_agent shape), '
        "a plain string, or a multimodal content block list. "
        'Example: agent.ainvoke({"messages": [{"role": "user", "content": "Hello"}]})'
    )
