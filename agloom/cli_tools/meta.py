"""Meta tools: ask user (HITL clarification) and session todo list."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from ..runtime.invocation_context import get_invocation_emitter, get_invocation_hitl_bridge


def make_meta_tools() -> list:
    @tool
    async def ask_user(question: str, choices: str | None = None) -> str:
        """Ask the human a clarification question over the AGP HITL channel (async).

        *choices* is optional JSON array string of suggested answers.
        """
        q = (question or "").strip()
        if not q:
            return "ask_user: empty question"
        parsed_choices: list[str] | None = None
        if choices:
            try:
                raw = json.loads(choices)
                if isinstance(raw, list):
                    parsed_choices = [str(x) for x in raw]
            except json.JSONDecodeError:
                parsed_choices = None
        bridge = get_invocation_hitl_bridge()
        if bridge is None:
            return "ask_user: no active HITL bridge for this invocation"
        return await bridge.request_clarification(q, choices=parsed_choices)

    @tool
    async def write_todos(items_json: str) -> str:
        """Replace the session todo list. *items_json* is a JSON array of objects with id, text, done."""
        raw = (items_json or "").strip()
        if not raw:
            return "write_todos: empty items_json"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return f"write_todos: invalid JSON ({exc})"
        if not isinstance(data, list):
            return "write_todos: expected a JSON array"
        norm: list[dict[str, Any]] = []
        for i, row in enumerate(data):
            if isinstance(row, str):
                norm.append({"id": str(i), "text": row, "done": False})
                continue
            if not isinstance(row, dict):
                continue
            tid = str(row.get("id") if row.get("id") is not None else i)
            text = str(row.get("text") or row.get("title") or "")
            done = bool(row.get("done") or row.get("completed"))
            norm.append({"id": tid, "text": text, "done": done})
        emitter = get_invocation_emitter()
        if emitter is None:
            return f"write_todos: stored locally ({len(norm)} items); no emitter to broadcast"
        try:
            emitter.emit_todos_updated(items=norm)
        except Exception as exc:
            return f"write_todos: emit failed: {exc}"
        return f"✓ todos updated ({len(norm)} items)"

    return [ask_user, write_todos]
