"""Safety path resolution for CLI filesystem tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from agloom.cli_tools.safety import SafetyContext, resolve_safe_path


def test_resolve_relative_stays_under_root(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    ctx = SafetyContext(root=root.resolve(), sandbox=True)
    p = resolve_safe_path("a.txt", ctx)
    assert p.is_file()


def test_resolve_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "x").write_text("nope", encoding="utf-8")
    ctx = SafetyContext(root=root.resolve(), sandbox=True)
    with pytest.raises(ValueError, match="escape"):
        resolve_safe_path("../secret/x", ctx)


def test_resolve_absolute_outside_root_blocked(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    outside = (tmp_path / "other.txt").resolve()
    outside.write_text("!", encoding="utf-8")
    ctx = SafetyContext(root=root.resolve(), sandbox=True)
    with pytest.raises(ValueError, match="outside"):
        resolve_safe_path(str(outside), ctx)
