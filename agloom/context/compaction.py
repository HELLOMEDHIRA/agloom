"""Compact message history under context pressure (full data stays in scratchpad)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage

from .tokens import estimate_messages_tokens
from .tool_scratchpad import ToolScratchpad, extract_ref_id_from_digest


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


def compact_messages_for_budget(
    messages: list[Any],
    scratchpad: ToolScratchpad,
    *,
    target_input_tokens: int,
    keep_recent_tool_rounds: int = 2,
) -> list[Any]:
    """Compress older tool results to stubs; keep recent rounds and user turns intact."""
    if not messages or estimate_messages_tokens(messages) <= target_input_tokens:
        return list(messages)

    out = list(messages)
    tool_indices = [i for i, m in enumerate(out) if isinstance(m, ToolMessage)]
    if len(tool_indices) <= keep_recent_tool_rounds:
        return out

    compactable = tool_indices[: -keep_recent_tool_rounds]
    for idx in compactable:
        msg = out[idx]
        if not isinstance(msg, ToolMessage):
            continue
        text = _tool_message_text(msg)
        if text.startswith("[compacted ") or _tool_message_text(msg).startswith("[agloom:tool_digest"):
            ref = _ensure_stored(scratchpad, msg)
            out[idx] = _replace_tool_content(msg, scratchpad.compact_stub(ref))
            continue
        ref = _ensure_stored(scratchpad, msg)
        out[idx] = _replace_tool_content(msg, scratchpad.compact_stub(ref))

    if estimate_messages_tokens(out) > target_input_tokens and len(compactable) < len(tool_indices):
        for idx in tool_indices[-keep_recent_tool_rounds:]:
            msg = out[idx]
            if not isinstance(msg, ToolMessage):
                continue
            text = _tool_message_text(msg)
            if len(text) > 4000 and not text.startswith("[compacted "):
                ref = _ensure_stored(scratchpad, msg)
                from .tool_scratchpad import build_tool_digest

                out[idx] = _replace_tool_content(
                    msg,
                    build_tool_digest(ref_id=ref, tool_name=msg.name or "tool", full_text=text),
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
