"""Built-in CLI/workspace tools (filesystem, shell, network, meta).

Merged by name in ``create_agent(..., cli_tools=...)`` (user tools override builtins).
When any builtin instance remains after merge, :data:`CLI_TOOLS_SYSTEM_APPENDIX` is appended
to a string ``system_prompt`` only (callable prompts unchanged).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .filesystem import make_filesystem_tools
from .meta import make_meta_tools
from .notebook import make_notebook_tools
from .safety import SafetyContext
from .shell import make_shell_tool, make_which_tools
from .task import make_task_tools
from .web import make_web_tools

CLI_TOOLS_SYSTEM_APPENDIX = """

=== Bundled workspace tools ===
- For each tool you invoke, **parameter names, types, and units** are defined by that tool's own description (the schema bundled with the model). Follow those definitions — do not invent semantics from memory.
"""

CLI_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "multi_edit",
        "glob_files",
        "delete_file",
        "move_file",
        "list_dir",
        "grep_files",
        "notebook_read",
        "notebook_edit",
        "mkdir",
        "rmdir",
        "which",
        "execute",
        "bash",
        "bash_background",
        "bash_background_status",
        "bash_background_stop",
        "fetch_url",
        "read_url_markdown",
        "web_search",
        "ask_user",
        "write_todos",
        "task",
    }
)


def get_cli_tools(
    *,
    working_dir: str | Path = ".",
    allow_shell: bool = True,
    allow_network: bool = True,
    sandbox: bool = True,
    task_agent_cell: list[Any | None] | None = None,
) -> list[Any]:
    """Return LangChain tool instances bound to *working_dir* and capability flags.

    Pass *task_agent_cell* as a one-element list; ``create_agent`` sets ``[0]`` to the
    ``UnifiedAgent`` after construction so the ``task`` tool can call ``adelegate``.
    """
    root = Path(working_dir).expanduser().resolve()
    ctx = SafetyContext(root=root, allow_shell=allow_shell, allow_network=allow_network, sandbox=sandbox)
    tools: list[Any] = []
    tools.extend(make_filesystem_tools(ctx))
    tools.extend(make_notebook_tools(ctx))
    tools.extend(make_which_tools())
    if allow_shell:
        tools.extend(make_shell_tool(ctx))
    tools.extend(make_web_tools(allow_network=allow_network))
    tools.extend(make_meta_tools())
    if task_agent_cell is not None:
        tools.extend(make_task_tools(task_agent_cell))
    return tools


def normalize_cli_tools_kwargs(cli_tools: dict[str, Any] | bool | None) -> dict[str, Any] | None:
    """Turn ``cli_tools=True`` into defaults; ``False``/``None`` → disabled."""
    if cli_tools is None or cli_tools is False:
        return None
    if cli_tools is True:
        return {
            "working_dir": ".",
            "allow_shell": True,
            "allow_network": True,
            "sandbox": True,
            "task_tool": True,
        }
    if isinstance(cli_tools, dict):
        out = dict(cli_tools)
        out.setdefault("working_dir", ".")
        out.setdefault("allow_shell", True)
        out.setdefault("allow_network", True)
        out.setdefault("sandbox", True)
        out.setdefault("task_tool", True)
        return out
    raise TypeError(f"cli_tools must be bool, dict, or None — got {type(cli_tools)!r}")


__all__ = [
    "CLI_TOOL_NAMES",
    "SafetyContext",
    "get_cli_tools",
    "normalize_cli_tools_kwargs",
]
