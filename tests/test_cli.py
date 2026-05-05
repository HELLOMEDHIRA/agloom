"""Tests for agloom_cli — config, tool loader, filesystem tools (no API keys)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agloom_cli.config import (
    get_system_prompt,
    get_thread_id,
    list_project_cleanup_dirs,
    load_config,
    remove_project_cleanup_dirs,
    set_cli_project_root,
)
from agloom_cli.tool_loader import discover_tools, tool
from agloom_cli.tools import read_file, write_file


def test_set_cli_project_root_creates_layout(tmp_path: Path) -> None:
    ag = set_cli_project_root(tmp_path)
    assert ag == tmp_path / ".agloom"
    assert (tmp_path / ".agloom" / "sessions").is_dir()
    assert (tmp_path / ".agloom" / "skills").is_dir()
    assert not (tmp_path / ".agloom" / "indexes").exists()
    assert (tmp_path / ".agloom" / "README.md").is_file()


def test_remove_project_cleanup_dirs(tmp_path: Path) -> None:
    (tmp_path / ".agloom").mkdir()
    (tmp_path / ".agsuperbrain").mkdir()
    (tmp_path / ".agloom" / "agloom.yaml").write_text("ai:\n  name: x\n", encoding="utf-8")
    found = list_project_cleanup_dirs(tmp_path)
    assert {p.name for p in found} == {".agloom", ".agsuperbrain"}
    removed = remove_project_cleanup_dirs(tmp_path)
    assert len(removed) == 2
    assert not (tmp_path / ".agloom").exists()
    assert not (tmp_path / ".agsuperbrain").exists()


def test_load_explicit_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate storage and project yaml so only the explicit file is merged."""
    isolated = tmp_path / "store"
    isolated.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", isolated)
    monkeypatch.setattr("agloom_cli.config.ProjectConfigPath", tmp_path / "no_project.yaml")
    cfg_path = tmp_path / "explicit.yaml"
    cfg_path.write_text("ai:\n  name: from-temp-file\n", encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.get("ai", {}).get("name") == "from-temp-file"


def test_load_missing_config_returns_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolated = tmp_path / "store"
    isolated.mkdir()
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", isolated)
    monkeypatch.setattr("agloom_cli.config.ProjectConfigPath", tmp_path / "no_project.yaml")
    cfg = load_config(Path("/non/existent/agloom-config-does-not-exist.yaml"))
    assert "ai" in cfg


def test_thread_id_from_config() -> None:
    cfg = {"session": {"current_session": "custom123"}}
    assert get_thread_id(cfg) == "custom123"


def test_thread_id_from_env() -> None:
    os.environ["AGLOOM_THREAD_ID"] = "env-thread"
    try:
        assert get_thread_id({}) == "env-thread"
    finally:
        del os.environ["AGLOOM_THREAD_ID"]


def test_thread_id_default_length() -> None:
    tid = get_thread_id({}, auto_save=False)
    assert len(tid) == 32
    int(tid, 16)


def test_get_system_prompt_nonempty() -> None:
    prompt = get_system_prompt()
    assert "autonomous" in prompt
    assert "programming" in prompt


def test_discover_tools_empty_dir(tmp_path: Path) -> None:
    assert discover_tools(tmp_path) == []


def test_discover_tools_nonexistent() -> None:
    assert discover_tools(Path("/nonexistent-agloom-tools-path")) == []


def test_tool_decorator_marks_function() -> None:
    @tool
    async def sample_tool(x: str) -> str:
        return x

    assert getattr(sample_tool, "_tool_marker", False) is True


@pytest.mark.asyncio
async def test_read_file_tool(tmp_path: Path) -> None:
    p = tmp_path / "hello.txt"
    p.write_text("Hello World", encoding="utf-8")
    result = await read_file(str(p))
    assert "Hello World" in result


@pytest.mark.asyncio
async def test_write_file_tool(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    result = await write_file(str(target), "Test content")
    assert "Successfully wrote" in result
    assert target.exists()
