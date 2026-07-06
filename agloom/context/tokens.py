"""Token estimation for context budgeting."""

from __future__ import annotations

import threading
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

_CHARS_PER_TOKEN = 4
_tiktoken_encoder: Any | None = None
_tiktoken_encoder_lock = threading.Lock()


def _get_tiktoken_encoder() -> Any | None:
    global _tiktoken_encoder
    if _tiktoken_encoder is not None:
        return _tiktoken_encoder
    with _tiktoken_encoder_lock:
        if _tiktoken_encoder is not None:
            return _tiktoken_encoder
        try:
            import tiktoken

            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tiktoken_encoder = None
    return _tiktoken_encoder


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken when available, else char approximation."""
    if not text:
        return 0
    enc = _get_tiktoken_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _message_to_text(msg: Any) -> str:
    if isinstance(msg, (HumanMessage, AIMessage, SystemMessage, ToolMessage)):
        content = msg.content
        name = getattr(msg, "name", None) or ""
    elif isinstance(msg, dict):
        content = msg.get("content", "")
        name = str(msg.get("name") or "")
    else:
        content = getattr(msg, "content", "")
        name = str(getattr(msg, "name", None) or "")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or block))
            else:
                parts.append(str(block))
        text = "\n".join(parts)
    else:
        text = str(content or "")
    if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
        text += "\n" + str(msg.tool_calls)
    if name:
        text = f"[{name}] {text}"
    return text


def estimate_messages_tokens(messages: list[Any]) -> int:
    """Rough token count for a LangChain message list."""
    return sum(count_tokens(_message_to_text(m)) for m in messages)
