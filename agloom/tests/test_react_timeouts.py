"""REACT wall-clock timeout helpers."""

from __future__ import annotations

from agloom.patterns.react import (
    _react_graph_wall_timeout,
    _react_llm_timeout,
    _react_timeout_failure_message,
)


def test_react_llm_timeout_honors_agent() -> None:
    assert _react_llm_timeout({"llm_timeout": 300}) == 300.0


def test_react_graph_timeout_scales_with_llm() -> None:
    assert _react_graph_wall_timeout({"llm_timeout": 120}) == 480.0
    assert _react_graph_wall_timeout({"llm_timeout": 300}) == 1200.0


def test_react_graph_timeout_explicit_override() -> None:
    assert _react_graph_wall_timeout({"llm_timeout": 120, "react_graph_timeout": 900}) == 900.0


def test_timeout_message_actionable() -> None:
    msg = _react_timeout_failure_message({"llm_timeout": 120}, wall_seconds=480, path="stream")
    assert "llm_timeout" in msg
    assert "react_graph_timeout" in msg
