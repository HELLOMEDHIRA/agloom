"""Persist HITL tool allowlist decisions (``decision=allowlist``) for stable runtime restarts."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any


def load_allowlist_from_session_marker(path: Path) -> set[str]:
    """Load ``hitl_tool_allowlist`` array from a session marker ``.json``."""
    try:
        raw = path.read_text(encoding="utf-8")
        data: Any = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(data, dict):
        return set()
    tools = data.get("hitl_tool_allowlist")
    if not isinstance(tools, list):
        return set()
    return {str(x).strip() for x in tools if str(x).strip()}


def save_allowlist_to_session_marker(path: Path, tools: set[str]) -> None:
    """Merge sorted ``hitl_tool_allowlist`` into an existing session marker JSON (preserve keys)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                existing = prev
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing["hitl_tool_allowlist"] = sorted(tools)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def hitl_allowlist_paths_for_runtime(
    args: Namespace,
    *,
    session_marker_json: Path | None,
    session_scoped: bool,
    cwd: Path | None = None,
) -> tuple[set[str], Path | None, Path | None]:
    """Resolve initial tool allowlist and persistence targets.

    Returns ``(tools, legacy_hitl_json_path, session_marker_json_path)``.

    **Session-scoped** (stdio): persist into ``session_marker_json`` only; seed from that file if
    present, otherwise from ``.agloom/hitl_tool_allowlist.json``.

    **Non-session** (e.g. WebSocket shared agent): legacy global JSON under ``.agloom/`` only.

    Explicit ``--hitl-allowlist-path`` always uses that legacy file.
    """
    cwd = cwd or Path.cwd()
    global_fallback = cwd / ".agloom" / "hitl_tool_allowlist.json"

    if getattr(args, "no_hitl_allowlist_persist", False):
        return set(), None, None

    raw_explicit = getattr(args, "hitl_allowlist_path", None)
    if isinstance(raw_explicit, str) and raw_explicit.strip():
        p = Path(raw_explicit).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return load_tool_allowlist(p), p, None

    if not session_scoped or session_marker_json is None:
        global_fallback.parent.mkdir(parents=True, exist_ok=True)
        return load_tool_allowlist(global_fallback), global_fallback, None

    session_marker_json.parent.mkdir(parents=True, exist_ok=True)
    if session_marker_json.is_file():
        tools = load_allowlist_from_session_marker(session_marker_json)
        if not tools:
            tools = load_tool_allowlist(global_fallback)
    else:
        tools = load_tool_allowlist(global_fallback)
    return tools, None, session_marker_json


def load_tool_allowlist(path: Path) -> set[str]:
    """Load tool names from JSON ``{"tools": ["execute", ...]}``; missing file → empty."""
    try:
        raw = path.read_text(encoding="utf-8")
        data: Any = json.loads(raw)
    except FileNotFoundError:
        return set()
    except (OSError, json.JSONDecodeError):
        return set()
    tools = data.get("tools") if isinstance(data, dict) else None
    if not isinstance(tools, list):
        return set()
    return {str(x).strip() for x in tools if str(x).strip()}


def save_tool_allowlist(path: Path, tools: set[str]) -> None:
    """Atomically write sorted unique tool names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"tools": sorted(tools)}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
