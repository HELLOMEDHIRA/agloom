"""ASCII-safe tool success lines (Windows cp1252 / AGP NDJSON must not require Unicode)."""

from __future__ import annotations


def tool_ok(detail: str) -> str:
    return f"OK: {detail}"
