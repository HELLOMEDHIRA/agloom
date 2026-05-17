"""Stdio reader limits and BOM handling."""

from __future__ import annotations

from agloom.runtime.__main__ import _stdin_line_too_long, _strip_utf8_bom


def test_strip_utf8_bom() -> None:
    assert _strip_utf8_bom("\ufeff{\"type\":\"command.ping\"}") == '{"type":"command.ping"}'


def test_stdin_line_too_long() -> None:
    assert _stdin_line_too_long(b"x" * 10, max_line_bytes=8) is True
    assert _stdin_line_too_long(b"short", max_line_bytes=8) is False
