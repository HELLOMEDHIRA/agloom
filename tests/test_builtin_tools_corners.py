"""Corner-case coverage for built-in CLI tools (path safety, HTTP guards, cwd stack)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agloom_cli.tools.filesystem import file_exists, write_file
from agloom_cli.tools.http import fetch_json, http_request
from agloom_cli.tools.web_search import web_search
from agloom_cli.tools.working_dir import (
    get_working_directory,
    path_absolute,
    path_exists,
    path_is_directory,
    path_is_file,
    push_working_directory,
)


@pytest.mark.asyncio
async def test_file_exists_blocks_traversal_outside_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = await file_exists("../outside")
    assert out.startswith("Error:")
    assert "traversal" in out.lower()


@pytest.mark.asyncio
async def test_path_exists_matches_file_exists_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "x.txt").write_text("a", encoding="utf-8")
    assert await path_exists("x.txt") == "true"
    assert await path_is_file("x.txt") == "true"
    assert await path_is_directory("x.txt") == "false"


@pytest.mark.asyncio
async def test_path_absolute_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    out = await path_absolute("sub/z")
    assert Path(out) == (tmp_path / "sub" / "z").resolve()


@pytest.mark.asyncio
async def test_push_working_directory_rolls_back_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    before = await get_working_directory()
    msg = await push_working_directory(str(tmp_path / "does_not_exist"))
    assert msg.startswith("Error:")
    after = await get_working_directory()
    assert before == after


@pytest.mark.asyncio
async def test_http_request_rejects_empty_url() -> None:
    out = await http_request("")
    assert "Error" in out and "url" in out.lower()


@pytest.mark.asyncio
async def test_fetch_json_rejects_empty_url() -> None:
    out = await fetch_json("  ")
    assert "Error" in out and "url" in out.lower()


@pytest.mark.asyncio
async def test_web_search_rejects_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    out = await web_search("")
    assert "Error" in out and "query" in out.lower()


@pytest.mark.asyncio
async def test_write_file_creates_nested_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    msg = await write_file("a/b/c.txt", "hi")
    assert "Successfully" in msg
    assert (tmp_path / "a" / "b" / "c.txt").read_text() == "hi"
