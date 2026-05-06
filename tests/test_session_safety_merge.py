"""Session + project ``safety`` merge and session YAML allowlist persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agloom_cli.config import (
    build_working_safety_for_thread,
    coerce_interrupt_before_tools_list,
    merge_tool_allowlist_into_session_yaml,
    session_config_yaml_path,
)
from agloom_cli.hitl import create_user_callback
from agloom_cli.hitl_allowlist import save_allowlist


def test_build_working_safety_unions_tool_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", tmp_path / ".agloom", raising=False)
    (tmp_path / ".agloom" / "sessions").mkdir(parents=True)
    sid = "a" * 32
    cfg = {
        "safety": {
            "require_approval": True,
            "tool_allowlist": ["run_shell"],
            "auto_approve": "",
        }
    }
    ypath = session_config_yaml_path(sid)
    ypath.write_text(
        yaml.dump(
            {"safety": {"tool_allowlist": ["read_file"]}},
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    merged = build_working_safety_for_thread(cfg, sid)
    assert set(merged.get("tool_allowlist", [])) == {"read_file", "run_shell"}
    assert merged.get("require_approval") is True


def test_coerce_interrupt_before_tools_default_tools_when_approval() -> None:
    assert coerce_interrupt_before_tools_list(None, require_approval=True) == ["tools"]
    assert coerce_interrupt_before_tools_list("", require_approval=True) == ["tools"]
    assert coerce_interrupt_before_tools_list(None, require_approval=False) is None


def test_merge_tool_allowlist_into_session_yaml_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", tmp_path / ".agloom", raising=False)
    (tmp_path / ".agloom" / "sessions").mkdir(parents=True)
    sid = "b" * 32
    merge_tool_allowlist_into_session_yaml(sid, "get_working_directory")
    merge_tool_allowlist_into_session_yaml(sid, "read_file")
    data = yaml.safe_load(session_config_yaml_path(sid).read_text(encoding="utf-8"))
    assert set(data["safety"]["tool_allowlist"]) == {"get_working_directory", "read_file"}


@pytest.mark.asyncio
async def test_strict_plus_file_still_honors_yaml_prefill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
