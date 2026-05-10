"""HITL tool allowlist JSON persistence."""

from __future__ import annotations

from pathlib import Path

from agloom.runtime.hitl_allowlist import load_tool_allowlist, save_tool_allowlist


def test_roundtrip_allowlist(tmp_path: Path) -> None:
    p = tmp_path / "al.json"
    save_tool_allowlist(p, {"execute", "bash"})
    assert load_tool_allowlist(p) == {"bash", "execute"}


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    assert load_tool_allowlist(tmp_path / "nope.json") == set()
