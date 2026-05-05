"""When resuming with ``--session``, hydrate LangGraph SessionMemory from ``sessions/<id>.json``."""

from __future__ import annotations

from typing import Any


def _cli_messages_to_turns(messages: list[dict]) -> list[dict]:
    """Convert CLI audit ``messages`` (role/content) into SessionMemory ``turns`` (q/a)."""
    turns: list[dict] = []
    pending_q: str | None = None
    for m in messages:
        role = str(m.get("role") or "").lower()
        content = str(m.get("content") or "")
        if role == "user":
            if pending_q is not None:
                turns.append({"q": pending_q[:500], "a": "(no assistant reply recorded)", "p": "cli"})
            pending_q = content
        elif role == "assistant":
            if pending_q is not None:
                turns.append({"q": pending_q[:500], "a": content[:1000], "p": "cli"})
                pending_q = None
            else:
                turns.append({"q": "(context)", "a": content[:1000], "p": "cli"})
    if pending_q is not None:
        turns.append({"q": pending_q[:500], "a": "(no assistant reply yet)", "p": "cli"})
    return turns


async def seed_session_memory_from_cli_json_if_empty(memory: Any, thread_id: str) -> None:
    """If the graph store has no turns for this thread, copy history from the session JSON file."""
    if memory is None or not thread_id:
        return

    from .config import get_session_history

    ns = memory._ns(thread_id)
    try:
        item = await memory.store.aget(ns, "turns")
        existing: list = item.value.get("turns", []) if item else []
    except Exception:
        existing = []
    if existing:
        return

    msgs = get_session_history(thread_id)
    if not msgs:
        return

    turns = _cli_messages_to_turns(msgs)
    if not turns:
        return

    max_turns = getattr(memory, "max_turns", 20)
    if len(turns) > max_turns:
        turns = turns[-max_turns:]

    await memory.store.aput(ns, "turns", {"turns": turns})
