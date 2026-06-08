"""Tool safety metadata drives HITL defaults."""

from __future__ import annotations

from agloom.cli_tools import CLI_TOOL_NAMES
from agloom.cli_tools.safety_metadata import (
    TOOL_SAFETY,
    ToolSafetyClass,
    tools_hitl_granular_interrupt,
    tools_path_scoped_allowlist,
)


def test_cli_tool_names_match_safety_registry() -> None:
    assert CLI_TOOL_NAMES == frozenset(TOOL_SAFETY)


def test_granular_interrupt_includes_mutating_and_shell() -> None:
    names = set(tools_hitl_granular_interrupt(allow_shell=True))
    assert "write_file" in names
    assert "bash" in names
    assert "read_file" not in names


def test_granular_interrupt_respects_allow_shell_false() -> None:
    names = set(tools_hitl_granular_interrupt(allow_shell=False))
    assert "bash" not in names
    assert "write_file" in names


def test_path_scoped_allowlist_read_tools() -> None:
    assert tools_path_scoped_allowlist() == frozenset({"read_file", "notebook_read"})


def test_read_only_tools_tagged() -> None:
    assert ToolSafetyClass.READ_ONLY in TOOL_SAFETY["grep_files"]
