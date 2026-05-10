"""Tests for Groq / provider tool_use_failed detection in ReAct."""

from __future__ import annotations

from agloom.patterns.react import (
    _exception_indicates_tool_use_failed,
    _extract_failed_generation_snippet,
    _human_message_after_tool_use_failed,
)


def test_tool_use_failed_from_body_code() -> None:
    class Exc(Exception):
        def __init__(self) -> None:
            self.body = {"error": {"code": "tool_use_failed", "message": "bad"}}

    assert _exception_indicates_tool_use_failed(Exc())


def test_tool_use_failed_from_string() -> None:
    assert _exception_indicates_tool_use_failed(RuntimeError('{"code":"tool_use_failed"}'))


def test_tool_use_failed_chain() -> None:
    class Inner(Exception):
        def __init__(self) -> None:
            super().__init__("inner")
            self.body = {"error": {"code": "tool_use_failed"}}

    try:
        raise RuntimeError("wrap") from Inner()
    except RuntimeError as e:
        assert _exception_indicates_tool_use_failed(e)


def test_not_tool_use_failed() -> None:
    assert not _exception_indicates_tool_use_failed(ValueError("rate limit"))


def test_extract_failed_generation() -> None:
    class Exc(Exception):
        def __init__(self) -> None:
            self.body = {
                "error": {
                    "code": "tool_use_failed",
                    "failed_generation": "The file was read successfully.",
                }
            }

    snip = _extract_failed_generation_snippet(Exc())
    assert "read successfully" in snip
    msg = _human_message_after_tool_use_failed(Exc())
    assert "tool_use_failed" in msg or "read successfully" in msg
    assert "Groq" in msg or "tool" in msg.lower()
