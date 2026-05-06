"""Session + project ``safety`` merge and session JSON allowlist persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agloom_cli.config import (
    build_working_safety_for_thread,
    coerce_interrupt_before_tools_list,
    merge_tool_allowlist_into_session_json,
    repair_empty_interrupt_before_tools_when_approval_on,
)
from agloom_cli.hitl import create_user_callback
from agloom_cli.hitl_allowlist import save_allowlist


def test_build_working_safety_unions_tool_allowlist_from_session_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", tmp_path / ".agloom", raising=False)
    (tmp_path / ".agloom" / "sessions").mkdir(parents=True)
    sid = "a" * 32
    jpath = tmp_path / ".agloom" / "sessions" / f"{sid}.json"
    jpath.write_text(
        json.dumps({"id": sid, "safety": {"tool_allowlist": ["read_file"]}}),
        encoding="utf-8",
    )
    cfg = {
        "safety": {
            "require_approval": True,
            "tool_allowlist": ["run_shell"],
            "auto_approve": "",
        }
    }
    merged = build_working_safety_for_thread(cfg, sid)
    assert set(merged.get("tool_allowlist", [])) == {"read_file", "run_shell"}
    assert merged.get("require_approval") is True


def test_build_working_safety_migrates_legacy_yaml_then_unlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", tmp_path / ".agloom", raising=False)
    (tmp_path / ".agloom" / "sessions").mkdir(parents=True)
    sid = "c" * 32
    ypath = tmp_path / ".agloom" / "sessions" / f"{sid}.yaml"
    ypath.write_text(
        yaml.dump(
            {"safety": {"tool_allowlist": ["read_file"]}},
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    cfg = {
        "safety": {
            "require_approval": True,
            "tool_allowlist": ["run_shell"],
            "auto_approve": "",
        }
    }
    merged = build_working_safety_for_thread(cfg, sid)
    assert not ypath.is_file()
    assert set(merged.get("tool_allowlist", [])) == {"read_file", "run_shell"}
    jpath = tmp_path / ".agloom" / "sessions" / f"{sid}.json"
    assert jpath.is_file()
    data = json.loads(jpath.read_text(encoding="utf-8"))
    assert set(data.get("safety", {}).get("tool_allowlist", [])) == {"read_file"}


def test_coerce_interrupt_before_tools_default_tools_when_approval() -> None:
    assert coerce_interrupt_before_tools_list(None, require_approval=True) == ["tools"]
    assert coerce_interrupt_before_tools_list("", require_approval=True) == ["tools"]
    assert coerce_interrupt_before_tools_list(None, require_approval=False) is None


def test_repair_empty_ibt_when_approval_on() -> None:
    assert repair_empty_interrupt_before_tools_when_approval_on([], require_approval=True) == (
        ["tools"],
        True,
    )
    assert repair_empty_interrupt_before_tools_when_approval_on(["run_shell"], require_approval=True) == (
        ["run_shell"],
        False,
    )
    assert repair_empty_interrupt_before_tools_when_approval_on([], require_approval=False) == ([], False)
    assert repair_empty_interrupt_before_tools_when_approval_on(None, require_approval=True) == (None, False)


def test_merge_tool_allowlist_into_session_json_roundtrip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", tmp_path / ".agloom", raising=False)
    (tmp_path / ".agloom" / "sessions").mkdir(parents=True)
    sid = "b" * 32
    merge_tool_allowlist_into_session_json(sid, "get_working_directory")
    merge_tool_allowlist_into_session_json(sid, "read_file")
    jpath = tmp_path / ".agloom" / "sessions" / f"{sid}.json"
    data = json.loads(jpath.read_text(encoding="utf-8"))
    assert set(data["safety"]["tool_allowlist"]) == {"get_working_directory", "read_file"}


@pytest.mark.asyncio
async def test_strict_plus_file_still_honors_allowlist_prefill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    p = tmp_path / "tool_allowlist.json"
    save_allowlist(p, {"tools": ["run_shell"], "patterns": [], "workers": []})
    cb = create_user_callback(
        auto_approve_tools=["write_file"],
        yaml_prefill_allow_tools=["read_file"],
        storage_root=tmp_path,
        allowlist_path=p,
        allowlist_strict_tools=True,
    )
    monkeypatch.setattr("agloom_cli.hitl.Prompt.ask", lambda *a, **k: "2")

    assert await cb("tool_interrupt_before", "Tool  : run_shell\nArgs  : {}") == "continue"
    assert await cb("tool_interrupt_before", "Tool  : read_file\nArgs  : {}") == "continue"
    assert await cb("tool_interrupt_before", "Tool  : write_file\nArgs  : {}") == "abort"
