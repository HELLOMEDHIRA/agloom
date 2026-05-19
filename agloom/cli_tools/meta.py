"""Meta tools: ask user (HITL clarification) and session todo list."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool


def make_meta_tools() -> list:
    # Lazy import: ``import agloom`` re-exports ``get_cli_tools`` from ``cli_tools``; loading
    # ``invocation_context`` here would drag AGP protocol + runtime HITL at package import time.
    from ..runtime.invocation_context import (
        get_invocation_agent_config,
        get_invocation_emitter,
        get_invocation_hitl_bridge,
    )

    @tool
    async def list_mcp_servers() -> str:
        """List MCP servers wired into this agloom session and their tools (name + short description).

        Use when the user asks which MCP servers are connected, what MCP tools exist, or what
        each MCP tool does. Does not open the Super-Brain graph database.

        Do **not** use agsuperbrain ``list_modules`` for this — that queries the Kuzu repo graph.
        """
        config = get_invocation_agent_config()
        if config is None:
            return "list_mcp_servers: no active agent session"
        from ..mcp_support import format_mcp_inventory_text, mcp_configured_server_names

        configured = mcp_configured_server_names(config)
        if configured and config.get("_mcp_servers") and not config.get("_mcp_session_attempted"):
            from ..unified_agent import _ensure_mcp_connected

            try:
                await _ensure_mcp_connected(config)
            except Exception as exc:
                return (
                    f"MCP connect failed: {exc}\n"
                    + format_mcp_inventory_text(
                        configured_names=configured,
                        server_rows=config.get("_mcp_server_rows"),
                    )
                )
        rows = config.get("_mcp_server_rows")
        return format_mcp_inventory_text(
            configured_names=configured,
            server_rows=rows if isinstance(rows, list) else None,
        )

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
        return f"OK: todos updated ({len(norm)} items)"

    return [list_mcp_servers, ask_user, write_todos]
