"""Safety classification for bundled CLI tools (HITL coalesce, policy, docs)."""

from __future__ import annotations

from enum import StrEnum


class ToolSafetyClass(StrEnum):
    READ_ONLY = "read_only"
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    SHELL = "shell"
    MUTATING = "mutating"
    META = "meta"


# Tags per built-in tool name. Extend when adding CLI tools.
TOOL_SAFETY: dict[str, frozenset[ToolSafetyClass]] = {
    "read_file": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.FILESYSTEM}),
    "grep_files": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.FILESYSTEM}),
    "glob_files": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.FILESYSTEM}),
    "list_dir": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.FILESYSTEM}),
    "which": frozenset({ToolSafetyClass.READ_ONLY}),
    "notebook_read": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.FILESYSTEM}),
    "write_file": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.FILESYSTEM}),
    "edit_file": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.FILESYSTEM}),
    "multi_edit": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.FILESYSTEM}),
    "delete_file": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.FILESYSTEM}),
    "move_file": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.FILESYSTEM}),
    "mkdir": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.FILESYSTEM}),
    "rmdir": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.FILESYSTEM}),
    "notebook_edit": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.FILESYSTEM}),
    "execute": frozenset({ToolSafetyClass.SHELL, ToolSafetyClass.MUTATING}),
    "bash": frozenset({ToolSafetyClass.SHELL, ToolSafetyClass.MUTATING}),
    "bash_background": frozenset({ToolSafetyClass.SHELL, ToolSafetyClass.MUTATING}),
    "bash_background_status": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.SHELL}),
    "bash_background_stop": frozenset({ToolSafetyClass.MUTATING, ToolSafetyClass.SHELL}),
    "fetch_url": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.NETWORK}),
    "read_url_markdown": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.NETWORK}),
    "web_search": frozenset({ToolSafetyClass.READ_ONLY, ToolSafetyClass.NETWORK}),
    "list_mcp_servers": frozenset({ToolSafetyClass.META}),
    "ask_user": frozenset({ToolSafetyClass.META}),
    "write_todos": frozenset({ToolSafetyClass.META}),
    "task": frozenset({ToolSafetyClass.META}),
}


def tool_safety_classes(tool_name: str) -> frozenset[ToolSafetyClass]:
    return TOOL_SAFETY.get(tool_name, frozenset())


def tools_path_scoped_allowlist() -> frozenset[str]:
    """Filesystem read tools where Allowlist (A) grants a path prefix, not the tool name."""
    return frozenset({"read_file", "notebook_read"} & set(TOOL_SAFETY))


def tools_hitl_granular_interrupt(*, allow_shell: bool = True) -> list[str]:
    """Default per-tool HITL interrupts when CLI tools are on but wildcard ``tools`` is off."""
    out: list[str] = []
    for name, tags in sorted(TOOL_SAFETY.items()):
        if ToolSafetyClass.SHELL in tags:
            if allow_shell and name != "bash_background_status":
                out.append(name)
            continue
        if ToolSafetyClass.MUTATING in tags:
            out.append(name)
    return out
