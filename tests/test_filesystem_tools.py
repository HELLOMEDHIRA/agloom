"""Tests for CLI filesystem built-in tools."""

from __future__ import annotations

import pytest

from agloom_cli.tools.filesystem import edit_file, grep_files, read_file


@pytest.mark.asyncio
async def test_read_file_offset_limit(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "t.txt"
    p.write_text("a\nb\nc\nd\n", encoding="utf-8")
    out = await read_file("t.txt", offset=2, limit=2)
    assert "2|b" in out
    assert "3|c" in out
    assert "4|" not in out


@pytest.mark.asyncio
async def test_read_file_full_preserves_raw_text(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "t.txt"
    p.write_text("one\n", encoding="utf-8")
    out = await read_file("t.txt")
    assert out == "one\n"


@pytest.mark.asyncio
async def test_edit_file_unique_replace(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "e.txt"
    p.write_text("hello world", encoding="utf-8")
    r = await edit_file("e.txt", "world", "there")
    assert "Successfully" in r
    assert p.read_text() == "hello there"


@pytest.mark.asyncio
async def test_edit_file_ambiguous(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "e.txt"
    p.write_text("x x", encoding="utf-8")
    r = await edit_file("e.txt", "x", "y")
    assert "ambiguous" in r.lower()


@pytest.mark.asyncio
async def test_grep_files_literal(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("foo = 1\nbar = 2\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("no match\n", encoding="utf-8")
    r = await grep_files("foo", ".", glob_pattern="*.py", regex=False)
    assert "a.py:1:" in r
    assert "foo" in r
