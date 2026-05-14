from __future__ import annotations

from agloom.patterns.hitl_read_file_dedupe import ReadFileHitlDeduper
from agloom.patterns.hitl_tool_coalesce import CompositeToolHitlCoalescer


def test_composite_delegates_read_file_strategy() -> None:
    c = CompositeToolHitlCoalescer([ReadFileHitlDeduper()])
    assert c.should_skip_hitl("read_file", {"path": "p", "limit": 50}) is False
    c.record_approval("read_file", {"path": "p", "offset": 0, "limit": 8000})
    assert c.should_skip_hitl("read_file", {"path": "p", "offset": 0, "limit": 100}) is True
