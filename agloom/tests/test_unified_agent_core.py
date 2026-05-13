"""Small, fast unit tests for ``unified_agent`` helpers (no full graph / LLM)."""

from __future__ import annotations

import pytest
from langchain_core.messages import SystemMessage

from agloom.models import DEFAULT_SYSTEM_PROMPT
from agloom.unified_agent import _wire_query_snapshot, normalize_tools, resolve_system_prompt


def test_resolve_system_prompt_none() -> None:
    assert resolve_system_prompt(None) == DEFAULT_SYSTEM_PROMPT


def test_resolve_system_prompt_empty_str() -> None:
    assert resolve_system_prompt("") == DEFAULT_SYSTEM_PROMPT


def test_resolve_system_message() -> None:
    assert resolve_system_prompt(SystemMessage(content="  X  ")) == "  X  "


def test_wire_query_snapshot_str() -> None:
    assert _wire_query_snapshot("hello") == "hello"


@pytest.mark.parametrize(
    "raw,expect_sub",
    [
        ([{"type": "text", "text": "a"}], "a"),
        ("flat", "flat"),
    ],
)
def test_wire_query_snapshot_multimodal(raw, expect_sub: str) -> None:
    out = _wire_query_snapshot(raw)
    assert expect_sub in out


def test_normalize_tools_empty() -> None:
    assert normalize_tools([]) == []


def test_normalize_tools_from_callable() -> None:
    def add_numbers(a: int, b: int) -> int:
        """Add *a* and *b*."""
        return a + b

    tools = normalize_tools([add_numbers])
    assert len(tools) == 1
    assert tools[0].name == "add_numbers"
