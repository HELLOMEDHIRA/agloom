"""Workspace bootstrap: starter ``.agloom/agloom.yaml`` and ``.agloom/sessions/*.json``."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agloom.runtime.workspace_bootstrap import (
    ensure_agloom_workspace,
    merge_session_marker_thread_turns,
    write_session_started_json,
)


def test_ensure_creates_yaml_and_sessions_dir(tmp_path: Path) -> None:
    sessions_dir, created = ensure_agloom_workspace(tmp_path)
    assert created is True
    assert sessions_dir == tmp_path / ".agloom" / "sessions"
    assert sessions_dir.is_dir()
    assert (tmp_path / ".agloom" / "rules").is_dir()
    assert (tmp_path / ".agloom" / "skills").is_dir()
    dot_yml = tmp_path / ".agloom" / "agloom.yaml"
    assert dot_yml.is_file()
    assert not (tmp_path / "agloom.yaml").exists()
    assert "model:" in dot_yml.read_text(encoding="utf-8")
    assert "agsuperbrain:mcp/agsuperbrain.yaml" in dot_yml.read_text(encoding="utf-8")
    assert (tmp_path / ".agloom" / "mcp" / "agsuperbrain.yaml").is_file()
    assert (tmp_path / ".agloom" / "rules" / "README.txt").is_file()

    sessions_dir2, created2 = ensure_agloom_workspace(tmp_path)
    assert created2 is False
    assert sessions_dir2 == sessions_dir


def test_migrate_root_only_yaml_into_dot_agloom(tmp_path: Path) -> None:
    root_y = tmp_path / "agloom.yaml"
    root_y.write_text("model: root-only\nai:\n  name: x\n", encoding="utf-8")
    sessions_dir, created = ensure_agloom_workspace(tmp_path)
    assert created is True
    nested = tmp_path / ".agloom" / "agloom.yaml"
    assert nested.is_file()
    assert "root-only" in nested.read_text(encoding="utf-8")
    assert "agsuperbrain:mcp/agsuperbrain.yaml" in nested.read_text(encoding="utf-8")
    assert sessions_dir == tmp_path / ".agloom" / "sessions"
    _, created2 = ensure_agloom_workspace(tmp_path)
    assert created2 is False


def test_ensure_adds_agsuperbrain_mcp_when_nested_yaml_has_none(tmp_path: Path) -> None:
    import yaml as pyyaml

    dot = tmp_path / ".agloom"
    dot.mkdir(parents=True)
    y = dot / "agloom.yaml"
    y.write_text("ai:\n  name: t\n  model: auto\n", encoding="utf-8")
    sessions_dir, created = ensure_agloom_workspace(tmp_path)
    assert created is False
    data = pyyaml.safe_load(y.read_text(encoding="utf-8"))
    servers = (data.get("mcp") or {}).get("servers") or []
    assert any(isinstance(x, str) and x.startswith("agsuperbrain:") for x in servers)
    assert sessions_dir == tmp_path / ".agloom" / "sessions"


def test_ensure_when_cwd_is_dot_agloom_dir(tmp_path: Path) -> None:
    """Runtime cwd inside ``project/.agloom`` → starter yaml at ``project/.agloom/agloom.yaml``."""
    dot = tmp_path / ".agloom"
    dot.mkdir()
    sessions_dir, created = ensure_agloom_workspace(dot)
    assert created is True
    assert sessions_dir == tmp_path / ".agloom" / "sessions"
    assert (dot / "agloom.yaml").is_file()
    assert not (tmp_path / "agloom.yaml").exists()
    assert (dot / "rules").is_dir()
    assert (dot / "skills").is_dir()
    assert not (dot / ".agloom").exists()


def test_ensure_when_cwd_nested_under_dot_agloom(tmp_path: Path) -> None:
    nested = tmp_path / ".agloom" / "sessions"
    nested.mkdir(parents=True)
    sessions_dir, created = ensure_agloom_workspace(nested)
    assert created is True
    assert sessions_dir == tmp_path / ".agloom" / "sessions"
    assert (tmp_path / ".agloom" / "agloom.yaml").is_file()
    assert not (tmp_path / "agloom.yaml").exists()
    assert (tmp_path / ".agloom" / "skills").is_dir()


def test_ensure_yaml_follows_absolute_agent_store_when_cwd_elsewhere(tmp_path: Path) -> None:
    """``graph_store`` under real project but process cwd elsewhere → starter yaml in that ``.agloom``."""
    wrong_cwd = tmp_path / "nested" / "launcher_cwd"
    wrong_cwd.mkdir(parents=True)
    agloom = tmp_path / ".agloom"
    agloom.mkdir(parents=True)
    db = agloom / "graph_store.sqlite"
    args = SimpleNamespace(
        agent_store_path=str(db.resolve()),
        store="none",
        store_path=None,
        memory_path=None,
        memory_type="",
    )
    sessions_dir, created = ensure_agloom_workspace(wrong_cwd, args=args)
    assert created is True
    assert (tmp_path / ".agloom" / "agloom.yaml").is_file()
    assert not (tmp_path / "agloom.yaml").exists()
    assert (tmp_path / ".agloom" / "rules").is_dir()
    assert sessions_dir == tmp_path / ".agloom" / "sessions"
    assert not (wrong_cwd / "agloom.yaml").exists()


def test_session_json_roundtrip(tmp_path: Path) -> None:
    sd = tmp_path / ".agloom" / "sessions"
    sd.mkdir(parents=True)
    p = write_session_started_json(
        sd,
        "sess_abc123",
        transport="stdio",
        thread="thread_x",
        record_cwd=tmp_path,
    )
    assert p is not None
    assert p.name == "sess_abc123.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["session_id"] == "sess_abc123"
    assert data["transport"] == "stdio"
    assert data["initial_thread"] == "thread_x"
    assert data["cwd"] == str(tmp_path.resolve())


def test_write_session_started_json_preserves_conversation_from_disk(tmp_path: Path) -> None:
    sd = tmp_path / ".agloom" / "sessions"
    sd.mkdir(parents=True)
    write_session_started_json(sd, "s1", transport="stdio", thread="t0", record_cwd=tmp_path)
    merge_session_marker_thread_turns(
        sd, "s1", thread_id="thread_a", turns=[{"q": "hi", "a": "yo", "p": "DIRECT"}]
    )
    write_session_started_json(
        sd,
        "s1",
        transport="stdio",
        thread="t0",
        record_cwd=tmp_path,
        extra={"effective_config": {"model": "openai:gpt-4o-mini"}},
    )
    data = json.loads((sd / "s1.json").read_text(encoding="utf-8"))
    assert data["effective_config"]["model"] == "openai:gpt-4o-mini"
    assert data["conversation"]["by_thread"]["thread_a"]["turns"][0]["q"] == "hi"


def test_safe_filename_for_odd_session_id(tmp_path: Path) -> None:
    sd = tmp_path / ".agloom" / "sessions"
    sd.mkdir(parents=True)
    p = write_session_started_json(sd, "weird/id", transport="stdio")
    assert p is not None
    assert p.name == "weird_id.json"


def test_session_marker_skips_when_sessions_dir_missing(tmp_path: Path) -> None:
    sd = tmp_path / ".agloom" / "sessions"
    assert write_session_started_json(sd, "sess_x", transport="stdio") is None
