from __future__ import annotations

import sys
from pathlib import Path

from agloom.patterns.hitl_read_file_dedupe import (
    ReadFileHitlDeduper,
    parse_read_file_path_offset_limit,
)


def test_parse_read_file_path_offset_limit() -> None:
    expected_path = str(Path("a.toml").resolve())
    if sys.platform == "win32":
        expected_path = expected_path.lower()
    assert parse_read_file_path_offset_limit({"path": "a.toml", "offset": 0, "limit": 100}) == (
        expected_path,
        0,
        100,
    )
    assert parse_read_file_path_offset_limit({"path": "  "}) is None


def test_deduper_skip_after_approval_smaller_second_limit() -> None:
    d = ReadFileHitlDeduper()
    assert d.should_skip_hitl("read_file", {"path": "p", "limit": 200}) is False
    d.record_approval("read_file", {"path": "p", "offset": 0, "limit": 8000})
    assert d.should_skip_hitl("read_file", {"path": "p", "offset": 0, "limit": 160}) is True


def test_deduper_no_skip_larger_second_limit() -> None:
    d = ReadFileHitlDeduper()
    d.record_approval("read_file", {"path": "p", "limit": 200})
    assert d.should_skip_hitl("read_file", {"path": "p", "offset": 0, "limit": 9000}) is False


def test_deduper_non_read_file_never_skips() -> None:
    d = ReadFileHitlDeduper()
    d.record_approval("read_file", {"path": "p", "limit": 5000})
    assert d.should_skip_hitl("write_file", {"path": "p"}) is False
