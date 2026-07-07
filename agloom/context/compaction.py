"""Compact message history under context pressure (full data stays in scratchpad)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from .tokens import estimate_messages_tokens
from .tool_scratchpad import (
    MAX_TOOL_WIRE_CHARS,
    ToolScratchpad,
    build_tool_digest,
    extract_ref_id_from_digest,
)


def _tool_message_text(msg: ToolMessage) -> str:
    return str(msg.content or "")


def _ensure_stored(scratchpad: ToolScratchpad, msg: ToolMessage) -> str:
    text = _tool_message_text(msg)
    existing = extract_ref_id_from_digest(text)
    if existing and scratchpad.get(existing):
        return existing
    if text.startswith("[compacted ") and "ref=" in text:
        import re

        m = re.search(r"ref=([a-f0-9]{8,16})", text)
        if m and scratchpad.get(m.group(1)):
            return m.group(1)
    art = scratchpad.store(msg.name or "tool", text, tool_call_id=getattr(msg, "tool_call_id", None))
    return art.ref_id


def _replace_tool_content(msg: ToolMessage, new_content: str) -> ToolMessage:
    return ToolMessage(
        content=new_content,
        tool_call_id=getattr(msg, "tool_call_id", None),
        name=getattr(msg, "name", None),
        id=getattr(msg, "id", None),
    )


def _force_wire_bound_tool_message(
    scratchpad: ToolScratchpad,
    msg: ToolMessage,
    *,
    max_wire_chars: int,
) -> ToolMessage:
    text = _tool_message_text(msg)
    if len(text) <= max_wire_chars:
        return msg
    if text.startswith("[compacted ") or text.startswith("[agloom:tool_digest"):
        ref = _ensure_stored(scratchpad, msg)
        stub = scratchpad.compact_stub(ref)
        if len(stub) <= max_wire_chars:
            return _replace_tool_content(msg, stub)
        return _replace_tool_content(
            msg,
            build_tool_digest(ref_id=ref, tool_name=msg.name or "tool", full_text=text, max_wire_chars=max_wire_chars),
        )
    ref = _ensure_stored(scratchpad, msg)
    return _replace_tool_content(
        msg,
        build_tool_digest(ref_id=ref, tool_name=msg.name or "tool", full_text=text, max_wire_chars=max_wire_chars),
    )


def compact_messages_for_budget(
    messages: list[Any],
    scratchpad: ToolScratchpad,
    *,
    target_input_tokens: int,
    keep_recent_tool_rounds: int = 2,
    max_wire_chars: int = MAX_TOOL_WIRE_CHARS,
) -> list[Any]:
    """Compress older tool results to stubs; bound oversized tools regardless of recency."""
    if not messages:
        return []

    out = list(messages)
    tool_indices = [i for i, m in enumerate(out) if isinstance(m, ToolMessage)]

    # Size pass: any tool message over max_wire_chars is digested/stubbed regardless of recency.
    for idx in tool_indices:
        msg = out[idx]
        if not isinstance(msg, ToolMessage):
            continue
        if len(_tool_message_text(msg)) > max_wire_chars:
            out[idx] = _force_wire_bound_tool_message(scratchpad, msg, max_wire_chars=max_wire_chars)

    if estimate_messages_tokens(out) <= target_input_tokens:
        return out

    if len(tool_indices) <= keep_recent_tool_rounds:
        return out

    compactable = tool_indices[: -keep_recent_tool_rounds]
    for idx in compactable:
        msg = out[idx]
        if not isinstance(msg, ToolMessage):
            continue
        text = _tool_message_text(msg)
        if text.startswith("[compacted ") or text.startswith("[agloom:tool_digest"):
            ref = _ensure_stored(scratchpad, msg)
            out[idx] = _replace_tool_content(msg, scratchpad.compact_stub(ref))
            continue
        ref = _ensure_stored(scratchpad, msg)
        out[idx] = _replace_tool_content(msg, scratchpad.compact_stub(ref))

    digest_min = max(500, target_input_tokens // 32)
    if estimate_messages_tokens(out) > target_input_tokens:
        for idx in tool_indices:
            msg = out[idx]
            if not isinstance(msg, ToolMessage):
                continue
            text = _tool_message_text(msg)
            if text.startswith("[compacted ") or text.startswith("[agloom:tool_digest"):
                continue
            if len(text) >= digest_min or len(text) > max_wire_chars:
                ref = _ensure_stored(scratchpad, msg)
                out[idx] = _replace_tool_content(
                    msg,
                    build_tool_digest(
                        ref_id=ref,
                        tool_name=msg.name or "tool",
                        full_text=text,
                        max_wire_chars=max_wire_chars,
                    ),
                )

    return out


def append_context_compaction_recap(
    messages: list[Any],
    *,
    scratchpad: ToolScratchpad,
) -> list[Any]:
    """Add a short human nudge after emergency compaction."""
    refs = list(scratchpad._artifacts.keys())[-8:]
    ref_hint = ", ".join(refs) if refs else "(see prior digests)"
    recap = HumanMessage(
        content=(
            "Context window was exceeded. Older tool outputs were moved to the scratchpad "
            f"(refs: {ref_hint}). Use recall_tool_artifact(ref_id=...) for full payloads. "
            "Continue the investigation using previews and targeted recalls."
        )
    )
    return list(messages) + [recap]
