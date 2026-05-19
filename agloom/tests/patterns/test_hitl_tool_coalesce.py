from __future__ import annotations

from agloom.patterns.hitl_tool_coalesce import (
    CompositeToolHitlCoalescer,
    ReadFileSubsetCoalescer,
    build_default_hitl_coalescer,
    reset_hitl_turn_coalescer,
)


def test_composite_delegates_read_file_strategy() -> None:
    c = CompositeToolHitlCoalescer([ReadFileSubsetCoalescer()])
    assert c.should_skip_hitl("read_file", {"path": "p", "limit": 50}) is False
    c.record_approval("read_file", {"path": "p", "offset": 0, "limit": 8000})
    assert c.should_skip_hitl("read_file", {"path": "p", "offset": 0, "limit": 100}) is True


def test_build_default_hitl_coalescer_read_file_subset_only() -> None:
    c = build_default_hitl_coalescer()
    c.record_approval("read_file", {"path": "a", "limit": 500})
    assert c.should_skip_hitl("read_file", {"path": "a", "limit": 100}) is True
    assert c.should_skip_hitl("grep_files", {"pattern": "x", "path": "."}) is False


def test_reset_hitl_turn_coalescer_clears_accept_memory() -> None:
    agent = {"_hitl_tool_coalescer": build_default_hitl_coalescer()}
    c = agent["_hitl_tool_coalescer"]
    c.record_approval("read_file", {"path": "a.toml", "offset": 0, "limit": 8000})
    assert c.should_skip_hitl("read_file", {"path": "a.toml", "offset": 0, "limit": 100}) is True
    reset_hitl_turn_coalescer(agent)
    assert c.should_skip_hitl("read_file", {"path": "a.toml", "offset": 0, "limit": 100}) is False
