"""Tests for :class:`agloom_cli.tools.LocalSandbox`."""

from __future__ import annotations

from pathlib import Path

import pytest

from agloom_cli.tools import BackendProtocol, LocalSandbox, SandboxBackendProtocol


def test_local_sandbox_read_pagination_0_indexed_skip(tmp_path: Path) -> None:
    sb = LocalSandbox(tmp_path)
    p = tmp_path / "a.txt"
    p.write_text("l1\nl2\nl3\n", encoding="utf-8")
    r0 = sb.read("a.txt", offset=0, limit=2)
    assert r0.error is None
    assert r0.file_data is not None
    assert r0.file_data["content"] == "l1\nl2"
    r1 = sb.read("a.txt", offset=1, limit=2)
    assert r1.file_data is not None
    assert r1.file_data["content"] == "l2\nl3"


def test_local_sandbox_write_fails_if_exists(tmp_path: Path) -> None:
    sb = LocalSandbox(tmp_path)
    (tmp_path / "x.txt").write_text("a", encoding="utf-8")
    w = sb.write("x.txt", "b")
    assert w.error is not None
    assert "exists" in w.error.lower()


def test_local_sandbox_edit_crlf(tmp_path: Path) -> None:
    sb = LocalSandbox(tmp_path)
    p = tmp_path / "crlf.txt"
    p.write_bytes(b"hello\r\nworld\r\n")
    e = sb.edit("crlf.txt", "hello\nworld", "hi\nworld", replace_all=False)
    assert e.error is None
    assert b"hi\r\nworld" in p.read_bytes()


def test_local_sandbox_path_escape(tmp_path: Path) -> None:
    sb = LocalSandbox(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        sb._safe("../../etc/passwd")


def test_local_sandbox_grep_literal(tmp_path: Path) -> None:
    sb = LocalSandbox(tmp_path)
    (tmp_path / "one.py").write_text("foo = 1\n", encoding="utf-8")
    g = sb.grep("foo", ".", "*.py")
    assert g.error is None
    assert g.matches is not None
    assert len(g.matches) == 1
    assert g.matches[0]["line"] == 1


def test_local_sandbox_is_protocol_instance(tmp_path: Path) -> None:
    sb = LocalSandbox(tmp_path)
    assert isinstance(sb, BackendProtocol)
    assert isinstance(sb, SandboxBackendProtocol)


def test_local_sandbox_virtual_absolute_path(tmp_path: Path) -> None:
    sb = LocalSandbox(tmp_path)
    (tmp_path / "n.txt").write_text("x", encoding="utf-8")
    r = sb.read("/n.txt", offset=0, limit=10)
    assert r.error is None
    assert r.file_data is not None
    assert r.file_data["content"] == "x"
