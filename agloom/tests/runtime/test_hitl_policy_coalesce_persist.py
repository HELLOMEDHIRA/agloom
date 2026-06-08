"""Path-scoped allowlist persistence in session markers."""

from __future__ import annotations

from pathlib import Path

from agloom.runtime.hitl_allowlist import (
    HitlAllowlistPolicy,
    build_session_hitl_coalescer,
    load_policy_from_session_marker,
    save_policy_to_session_marker,
)


def test_read_file_allowlist_is_path_scoped_not_global() -> None:
    policy = HitlAllowlistPolicy()
    policy.apply_allowlist_decision("read_file", {"path": "foo.txt"})
    assert "read_file" not in policy.global_tools()
    assert policy.allows("read_file", {"path": "foo.txt"})
    assert not policy.allows("read_file", {"path": "bar.txt"})


def test_bash_allowlist_remains_global_tool() -> None:
    policy = HitlAllowlistPolicy()
    policy.apply_allowlist_decision("bash", {"cmd": "ls"})
    assert "bash" in policy.global_tools()
    assert policy.allows("bash", {})


def test_save_policy_roundtrip_in_session_marker(tmp_path: Path) -> None:
    marker = tmp_path / "sess.json"
    marker.write_text("{}", encoding="utf-8")
    policy = HitlAllowlistPolicy()
    policy.apply_allowlist_decision("read_file", {"path": "src/main.py"})
    policy.add_global_tool("grep_files")
    save_policy_to_session_marker(marker, policy)
    loaded = load_policy_from_session_marker(marker)
    assert loaded.global_tools() == {"grep_files"}
    assert loaded.allows("read_file", {"path": "src/main.py"})


def test_build_session_hitl_coalescer_is_fresh() -> None:
    c = build_session_hitl_coalescer()
    c.record_approval("read_file", {"path": "x.toml", "limit": 500})
    c2 = build_session_hitl_coalescer()
    assert c2.should_skip_hitl("read_file", {"path": "x.toml", "limit": 100}) is False
