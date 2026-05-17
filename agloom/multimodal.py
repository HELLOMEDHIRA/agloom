"""Multimodal user turns and vision heuristics (core library).

For ``command.invoke`` file staging used by the AGP runtime, see
:mod:`agloom.runtime.attachment_stage`.
"""

from __future__ import annotations

import re
from typing import Any


def model_id_supports_vision(model_id: str | None) -> bool:
    """Best-effort guess whether *model_id* supports image input (not vendor-authoritative)."""
    if not model_id:
        return False
    m = model_id.lower()
    if any(x in m for x in ("gpt-3.5", "gpt-35", "text-davinci")):
        return False
    if any(
        x in m
        for x in (
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-4-vision",
            "claude-3",
            "claude-sonnet-4",
            "gemini",
            "llama-3.2-90b",
            "llama-3.2-11b",
            "llama3.2-90b",
            "llama3.2-11b",
            "qwen-vl",
            "pixtral",
        )
    ):
        return True
    if re.search(r"gpt-4[\w.-]*vision|vision-preview|image[_-]input|multimodal", m):
        return True
    return False


def content_blocks_to_text(content: Any) -> str:
    """Normalize ``AIMessage.content`` (str, None, or provider content blocks) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype in ("image", "image_url", "input_audio", "video", "file"):
                    continue
                if btype == "text" and "text" in block:
                    parts.append(str(block.get("text", "")))
                elif isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "".join(parts)
    return str(content)


def text_from_user_turn(user_turn: str | list[dict[str, Any]]) -> str:
    """Plain text from a string user message or LangChain-style content blocks."""
    if isinstance(user_turn, str):
        return user_turn
    parts: list[str] = []
    for block in user_turn:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            t = block.get("text")
            if isinstance(t, str):
                parts.append(t)
    return "\n".join(parts) if parts else str(user_turn)


def merge_context_into_user_turn(augmented_text: str, original_user: Any) -> str | list[dict[str, Any]]:
    """Merge classifier/memory text with the original turn, preserving ``image_url`` blocks."""
    if isinstance(original_user, dict):
        images: list[dict[str, Any]] = []
        if original_user.get("type") == "image_url":
            images.append(original_user)
        for b in original_user.get("content") or []:
            if isinstance(b, dict) and b.get("type") == "image_url":
                images.append(b)
        if not images:
            return augmented_text
        return [{"type": "text", "text": augmented_text}, *images]
    if isinstance(original_user, str):
        return augmented_text
    images: list[dict[str, Any]] = []
    for b in original_user:
        if isinstance(b, dict) and b.get("type") == "image_url":
            images.append(b)
    if not images:
        return augmented_text
    return [{"type": "text", "text": augmented_text}, *images]


def guess_model_id(agent: Any) -> str | None:
    """Best-effort model id string from ``agent.config['llm']``."""
    llm_obj = getattr(agent, "config", {}).get("llm")
    if llm_obj is None:
        return None
    mid = getattr(llm_obj, "model_name", None) or getattr(llm_obj, "model", None)
    return str(mid) if mid else type(llm_obj).__name__
