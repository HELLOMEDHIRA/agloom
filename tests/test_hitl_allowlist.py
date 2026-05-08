"""Tests for HITL allowlist persistence and parsing helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agloom_cli.hitl import _parse_pattern_name, _parse_tool_name, _parse_worker_id, create_user_callback
from agloom_cli.hitl_allowlist import load_allowlist, merge_allowlist_file, resolve_allowlist_path, save_allowlist


def test_load_save_allowlist_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "tool_allowlist.json"
    save_allowlist(p, {"tools": ["run_shell"], "patterns": ["REACT"], "workers": ["w1"]})
    assert load_allowlist(p) == {
        "tools": ["run_shell"],
        "patterns": ["REACT"],
        "workers": ["w1"],
    }


def test_resolve_allowlist_path_basename_only(tmp_path: Path) -> None:
    root = tmp_path / ".agloom"
    root.mkdir()
    p = resolve_allowlist_path(root, "my_allow.json")
    assert p == root / "my_allow.json"
    assert p.name == "my_allow.json"


def test_resolve_allowlist_path_rejects_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / ".agloom"
    root.mkdir()
    for bad in ("../evil.json", "a/b.json", "x\\y.json"):
        with pytest.raises(ValueError):
            resolve_allowlist_path(root, bad)


def test_merge_allowlist_merges_and_dedupes(tmp_path: Path) -> None:
    p = tmp_path / "a.json"
    save_allowlist(p, {"tools": ["a"], "patterns": [], "workers": []})
    merge_allowlist_file(p, tools=["b", "a"], patterns=["REACT"], workers=["x"])
    data = json.loads(p.read_text(encoding="utf-8"))
    assert set(data["tools"]) == {"a", "b"}
    assert data["patterns"] == ["REACT"]
    assert data["workers"] == ["x"]


def test_parse_tool_worker_pattern() -> None:
    assert _parse_tool_name("Agent : x\nTool  : run_shell\nArgs  : {}") == "run_shell"
    assert _parse_worker_id("Worker  : researcher\nTask  : hi") == "researcher"
    assert _parse_pattern_name("Foo INTERRUPT-BEFORE [REACT]\nQuery: q") == "REACT"


@pytest.mark.asyncio
async def test_callback_tool_allowlisted_skips_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cb = create_user_callback(
        auto_approve_tools=[],
        yaml_prefill_allow_tools=["write_file"],
    )
    called: list[str] = []

    def boom(*_a, **_k):
        called.append("prompt")
        return "2"

    monkeypatch.setattr("agloom_cli.hitl.Prompt.ask", boom)
    out = await cb(
        "tool_interrupt_before",
        "Agent : A\nTool  : write_file\nArgs  : {}",
    )
    assert out == "continue"
    assert called == []


@pytest.mark.asyncio
async def test_tool_interrupt_before_accepts_dict_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Middleware-style dict (tool_name, tool_call_id, detail) is supported alongside legacy str."""
    cb = create_user_callback()
    monkeypatch.setattr("agloom_cli.hitl.Prompt.ask", lambda *a, **k: "2")
    payload = {
        "tool_name": "run_shell",
        "tool_call_id": "tc-test-1",
        "agent_name": "A",
        "args": {},
        "detail": "Agent : A\nTool  : run_shell\nArgs  : {}",
    }
    out = await cb("tool_interrupt_before", payload)
    assert out == "abort"


@pytest.mark.asyncio
async def test_callback_tool_reject_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cb = create_user_callback()

    monkeypatch.setattr("agloom_cli.hitl.Prompt.ask", lambda *a, **k: "2")
    out = await cb(
        "tool_interrupt_before",
        "Agent : A\nTool  : run_shell\nArgs  : {}",
    )
    assert out == "abort"


@pytest.mark.asyncio
async def test_callback_unions_yaml_prefill_and_auto_approve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tools in yaml_prefill_allow_tools or auto_approve_tools skip the prompt."""
    cb = create_user_callback(
        auto_approve_tools=["read_file", "write_file"],
        yaml_prefill_allow_tools=["run_shell"],
    )
    monkeypatch.setattr("agloom_cli.hitl.Prompt.ask", lambda *a, **k: "2")

    assert await cb("tool_interrupt_before", "Tool  : run_shell\nArgs  : {}") == "continue"
    assert await cb("tool_interrupt_before", "Tool  : read_file\nArgs  : {}") == "continue"
    assert await cb("tool_interrupt_before", "Tool  : write_file\nArgs  : {}") == "continue"
    assert await cb("tool_interrupt_before", "Tool  : delete_everything\nArgs  : {}") == "abort"


@pytest.mark.asyncio
async def test_always_allow_session_json_write_error_still_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Session JSON allowlist write failure must not abort the in-flight tool."""
    store = tmp_path / ".agloom"
    store.mkdir()
    (store / "sessions").mkdir(parents=True)
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    sid = "b" * 32
    cb = create_user_callback(
        persist_allowlist_session_id=sid,
    )
    monkeypatch.setattr("agloom_cli.hitl.Prompt.ask", lambda *a, **k: "3")

    def boom_session(*_a, **_k):
        raise OSError("session write failed")

    monkeypatch.setattr("agloom_cli.hitl.merge_tool_allowlist_into_session_json", boom_session)
    out = await cb("tool_interrupt_before", "Tool  : read_file\nArgs  : {}")
    assert out == "continue"


@pytest.mark.asyncio
async def test_always_allow_persists_to_session_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Triple-gate choice 3 appends tool to ``sessions/<id>.json`` ``safety.tool_allowlist``."""
    store = tmp_path / ".agloom"
    store.mkdir()
    (store / "sessions").mkdir(parents=True)
    monkeypatch.setattr("agloom_cli.config._cli_storage_dir", store)
    sid = "a" * 32
    cb = create_user_callback(
        persist_allowlist_session_id=sid,
    )
    monkeypatch.setattr("agloom_cli.hitl.Prompt.ask", lambda *a, **k: "3")

    out = await cb("tool_interrupt_before", "Tool  : my_tool\nArgs  : {}")
    assert out == "continue"
    jpath = store / "sessions" / f"{sid}.json"
    data = json.loads(jpath.read_text(encoding="utf-8"))
    assert "my_tool" in (data.get("safety") or {}).get("tool_allowlist", [])
