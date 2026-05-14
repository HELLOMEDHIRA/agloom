"""``read_file``-only coalescer: skip L2 HITL when a second read is the same path/offset with ``limit`` ≤ a recent approval.

Registered via ``CompositeToolHitlCoalescer`` in L2 middleware — do not generalize this logic to other
tools without a separate, reviewed strategy (writes/shell/network are not subset-safe by args alone).
"""

from __future__ import annotations

from time import monotonic
from typing import Any

READ_FILE_HITL_COALESCE_SEC = 35.0


def parse_read_file_path_offset_limit(tool_args: dict[str, Any]) -> tuple[str, int, int] | None:
    raw = tool_args.get("path")
    if not isinstance(raw, str):
        return None
    path = raw.strip()
    if not path:
        return None
    try:
        off = int(tool_args.get("offset") or 0)
    except (TypeError, ValueError):
        off = 0
    try:
        lim = int(tool_args.get("limit") if tool_args.get("limit") is not None else 8000)
    except (TypeError, ValueError):
        lim = 8000
    return path, off, max(1, lim)


class ReadFileHitlDeduper:
    __slots__ = ("_recent",)

    def __init__(self) -> None:
        self._recent: list[tuple[float, str, int, int]] = []

    def _prune(self, now: float) -> None:
        keep = READ_FILE_HITL_COALESCE_SEC
        self._recent = [t for t in self._recent if now - t[0] <= keep]

    def should_skip_hitl(self, tool_name: str, tool_args: dict[str, Any]) -> bool:
        if tool_name != "read_file":
            return False
        key = parse_read_file_path_offset_limit(tool_args)
        if key is None:
            return False
        path, off, new_lim = key
        now = monotonic()
        self._prune(now)
        for ts, p, o, approved_lim in self._recent:
            if now - ts > READ_FILE_HITL_COALESCE_SEC:
                continue
            if p == path and o == off and new_lim <= approved_lim:
                return True
        return False

    def record_approval(self, tool_name: str, tool_args: dict[str, Any]) -> None:
        if tool_name != "read_file":
            return
        key = parse_read_file_path_offset_limit(tool_args)
        if key is None:
            return
        path, off, lim = key
        now = monotonic()
        self._prune(now)
        self._recent.append((now, path, off, lim))
