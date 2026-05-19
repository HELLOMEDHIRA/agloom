from __future__ import annotations

import sys
from pathlib import Path

from agloom.patterns.hitl_tool_coalesce import (
    ReadFileSubsetCoalescer,
    parse_read_file_scope,
    read_file_scope_is_subset,
)


def test_parse_read_file_scope() -> None:
    expected_path = str(Path("a.toml").resolve())
    if sys.platform == "win32":
        expected_path = expected_path.lower()
    assert parse_read_file_scope({"path": "a.toml", "offset": 0, "limit": 100}) == (
        expected_path,
        0,
        100,
        None,
    )
    capped = parse_read_file_scope({"path": "pyproject.toml", "line_cap": 20, "limit": 4000})
    assert capped is not None
    assert capped[3] == 20
    assert parse_read_file_scope({"path": "  "}) is None


def test_read_file_scope_is_subset_line_cap() -> None:
    base = ("p", 0, 8000, 20)
    assert read_file_scope_is_subset(("p", 0, 8000, 10), base) is True
    assert read_file_scope_is_subset(("p", 0, 8000, None), base) is False
    assert read_file_scope_is_subset(("p", 0, 4000, 20), base) is True


def test_coalescer_skip_after_approval_smaller_second_limit() -> None:
    d = ReadFileSubsetCoalescer()
    assert d.should_skip_hitl("read_file", {"path": "p", "limit": 200}) is False
    d.record_approval("read_file", {"path": "p", "offset": 0, "limit": 8000})
    assert d.should_skip_hitl("read_file", {"path": "p", "offset": 0, "limit": 160}) is True


def test_coalescer_skip_line_cap_after_same_path_approval() -> None:
    d = ReadFileSubsetCoalescer()
    d.record_approval("read_file", {"path": "pyproject.toml", "offset": 0, "limit": 8000, "line_cap": 20})
    assert (
        d.should_skip_hitl(
            "read_file",
            {"path": "pyproject.toml", "offset": 0, "limit": 8000, "line_cap": 20},
        )
        is True
    )


def test_coalescer_no_skip_larger_second_limit() -> None:
    d = ReadFileSubsetCoalescer()
    d.record_approval("read_file", {"path": "p", "limit": 200})
    assert d.should_skip_hitl("read_file", {"path": "p", "offset": 0, "limit": 9000}) is False


def test_coalescer_non_read_file_never_skips() -> None:
    d = ReadFileSubsetCoalescer()
    d.record_approval("read_file", {"path": "p", "limit": 5000})
    assert d.should_skip_hitl("write_file", {"path": "p"}) is False
