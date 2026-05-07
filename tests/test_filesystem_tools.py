"""Tests for CLI filesystem built-in tools."""

from __future__ import annotations

import pytest

from agloom_cli.safety_limits import READ_FILE_ABS_MAX_BYTES, READ_FILE_FULL_NO_LIMIT_MAX_LINES
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
async def test_read_file_coerces_string_numeric_args(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Models often emit string numbers in JSON tool args."""
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "t.txt"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    out = await read_file("t.txt", offset="2", limit="2")  # type: ignore[arg-type]
    assert "2|b" in out
    assert "3|c" in out


@pytest.mark.asyncio
async def test_read_file_offset_past_eof_tail_with_limit(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLMs often use a guessed offset for 'last N lines'; clamp to tail when offset > line count."""
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "short.toml"
    p.write_text("l1\nl2\nl3\nl4\nl5\nl6\nl7\nl8\nl9\n", encoding="utf-8")
    out = await read_file("short.toml", offset=21, limit=20)
    for i in range(1, 10):
        assert f"{i}|l{i}" in out
    assert "Error" not in out


@pytest.mark.asyncio
async def test_read_file_offset_past_eof_no_limit_returns_full_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "t.txt"
    p.write_text("only\n", encoding="utf-8")
    out = await read_file("t.txt", offset=99, limit=None)
    assert out == "only\n"


@pytest.mark.asyncio
async def test_read_file_offset_none_defaults_to_start(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "t.txt"
    p.write_text("x\n", encoding="utf-8")
    out = await read_file("t.txt", offset=None, limit=None)
    assert out == "x\n"


@pytest.mark.asyncio
async def test_read_file_full_preserves_raw_text(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "t.txt"
    p.write_text("one\n", encoding="utf-8")
    out = await read_file("t.txt")
    assert out == "one\n"


@pytest.mark.asyncio
async def test_read_file_unbounded_envelope_when_very_long(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No offset/limit: structured incomplete envelope + line preview when over budget."""
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "long.txt"
    n_lines = READ_FILE_FULL_NO_LIMIT_MAX_LINES + 500
    p.write_text("\n".join(f"L{i}" for i in range(n_lines)) + "\n", encoding="utf-8")
    out = await read_file("long.txt")
    assert "[agloom:tool_result]" in out
    assert "complete=false" in out
    assert "read_file_line_budget_unbounded" in out
    assert "L0" in out
    assert f"L{READ_FILE_FULL_NO_LIMIT_MAX_LINES - 1}" in out
    assert f"L{n_lines - 1}" not in out


@pytest.mark.asyncio
async def test_read_file_explicit_limit_over_cap_envelope(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agloom_cli.safety_limits import READ_FILE_MAX_LINES_PER_CALL

    monkeypatch.chdir(tmp_path)
    p = tmp_path / "wide.txt"
    p.write_text("\n".join(f"row{i}" for i in range(5000)) + "\n", encoding="utf-8")
    out = await read_file("wide.txt", offset=1, limit=99999)
    assert "[agloom:tool_result]" in out
    assert "complete=false" in out
    assert "read_file_limit_too_large" in out
    assert READ_FILE_MAX_LINES_PER_CALL > 0
    assert "|row0" not in out


@pytest.mark.asyncio
async def test_read_file_rejects_max_size_above_abs_cap(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "tiny.txt"
    p.write_text("x\n", encoding="utf-8")
    out = await read_file("tiny.txt", max_size=READ_FILE_ABS_MAX_BYTES + 1)
    assert "Error" in out
    assert "10485761" in out and "max_size" in out.lower()


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
