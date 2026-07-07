"""Reserved Agloom tool names — shared by create_agent and MCP connect."""

from __future__ import annotations

from langchain_core.tools import BaseTool

AGLOOM_TOOL_PREFIX = "agloom_"

TOOL_SAVE_MEMORY = f"{AGLOOM_TOOL_PREFIX}save_memory"
TOOL_RECALL_MEMORY = f"{AGLOOM_TOOL_PREFIX}recall_memory"
TOOL_LOAD_SKILL = f"{AGLOOM_TOOL_PREFIX}load_skill"
TOOL_RECALL_TOOL_ARTIFACT = f"{AGLOOM_TOOL_PREFIX}recall_tool_artifact"

RESERVED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        TOOL_SAVE_MEMORY,
        TOOL_RECALL_MEMORY,
        TOOL_LOAD_SKILL,
        TOOL_RECALL_TOOL_ARTIFACT,
    }
)

MEMORY_TOOL_NAMES: frozenset[str] = frozenset({TOOL_SAVE_MEMORY, TOOL_RECALL_MEMORY})


def is_agloom_reserved_tool_name(name: str) -> bool:
    """True for Agloom-owned tools and any caller/MCP tool in the agloom_ namespace."""
    return name.startswith(AGLOOM_TOOL_PREFIX)


def check_reserved_tool_names(tools: list[BaseTool]) -> None:
    """Raise ValueError if any tool collides with agloom's internal tool namespace."""
    collisions = sorted({t.name for t in tools if is_agloom_reserved_tool_name(t.name)})
    if collisions:
        names = ", ".join(collisions)
        raise ValueError(
            f"Tool name(s) {names} are reserved by agloom for internal use. "
            f"Please rename your tool(s) to avoid conflicts. "
            f"Reserved prefix: {AGLOOM_TOOL_PREFIX!r} "
            f"(examples: {sorted(RESERVED_TOOL_NAMES)})"
        )
