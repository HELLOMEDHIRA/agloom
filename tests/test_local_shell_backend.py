"""Tests for :class:`agloom_cli.tools.LocalShellBackend`."""

from __future__ import annotations

from pathlib import Path

from agloom_cli.tools import LocalShellBackend


def test_local_shell_execute_echo(tmp_path: Path) -> None:
    be = LocalShellBackend(tmp_path, inherit_env=True)
    r = be.execute('echo hello')
    assert r.exit_code == 0
    assert "hello" in r.output


def test_local_shell_stderr_tagged(tmp_path: Path) -> None:
    be = LocalShellBackend(tmp_path, inherit_env=True)
    r = be.execute('python -c "import sys; sys.stderr.write(\'err_line\\n\')"')
    assert r.exit_code == 0
    assert "[stderr]" in r.output
    assert "err_line" in r.output


def test_local_shell_nonzero_exit(tmp_path: Path) -> None:
    be = LocalShellBackend(tmp_path, inherit_env=True)
    r = be.execute('python -c "raise SystemExit(7)"')
    assert r.exit_code == 7
    assert "Exit code: 7" in r.output


def test_local_shell_truncation(tmp_path: Path) -> None:
    be = LocalShellBackend(tmp_path, inherit_env=True, max_output_bytes=20)
    r = be.execute("python -c \"print('x'*100)\"")
    assert r.truncated is True
    assert "truncated" in r.output.lower()


def test_local_shell_inherits_read_under_root(tmp_path: Path) -> None:
    be = LocalShellBackend(tmp_path, inherit_env=True)
    (tmp_path / "f.txt").write_text("inside", encoding="utf-8")
    rd = be.read("f.txt", offset=0, limit=10)
    assert rd.error is None
    assert rd.file_data is not None
    assert rd.file_data["content"] == "inside"


def test_local_shell_unique_id(tmp_path: Path) -> None:
    a = LocalShellBackend(tmp_path, inherit_env=True)
    b = LocalShellBackend(tmp_path, inherit_env=True)
    assert a.id.startswith("local-")
    assert a.id != b.id
