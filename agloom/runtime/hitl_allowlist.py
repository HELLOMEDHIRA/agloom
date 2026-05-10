"""Persist HITL tool allowlist decisions (``decision=allowlist``) for stable runtime restarts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
