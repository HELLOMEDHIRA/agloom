"""Reserved tool name guard — user tools only, not Agloom-injected internals."""

from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool
from langgraph.store.memory import InMemoryStore
from unittest.mock import AsyncMock, MagicMock

from agloom.memory.store import LongTermStore
from agloom.src.reserved_tools import (
    TOOL_LOAD_SKILL,
    TOOL_RECALL_MEMORY,
    TOOL_RECALL_TOOL_ARTIFACT,
    TOOL_SAVE_MEMORY,
)
from agloom.src.unified_agent import create_agent


def _tool(name: str) -> StructuredTool:
    def fn() -> str:
        """stub"""
        return "ok"

    return StructuredTool.from_function(fn, name=name, description=f"{name} tool")


@pytest.mark.asyncio
async def test_create_agent_with_memory_tools_enabled() -> None:
    """Agloom-injected memory tools must not trip the reserved-name guard."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    store = LongTermStore(store=InMemoryStore())

    agent = await create_agent(
        model=llm,
        tools=[_tool("ping")],
        store=store,
        enable_memory_tools=True,
        name="memory-tools-ok",
    )

    names = [t.name for t in agent.config["tools"]]
    assert TOOL_SAVE_MEMORY in names
    assert TOOL_RECALL_MEMORY in names
    assert TOOL_RECALL_TOOL_ARTIFACT in names


@pytest.mark.asyncio
async def test_create_agent_rejects_user_reserved_tool_names() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    store = LongTermStore(store=InMemoryStore())

    with pytest.raises(ValueError, match="agloom_save_memory.*reserved"):
        await create_agent(
            model=llm,
            tools=[_tool(TOOL_SAVE_MEMORY)],
            store=store,
            enable_memory_tools=False,
            name="reserved-collision",
        )


@pytest.mark.asyncio
async def test_create_agent_rejects_agloom_prefix_impersonation() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())

    with pytest.raises(ValueError, match="agloom_fake_tool.*reserved"):
        await create_agent(
            model=llm,
            tools=[_tool("agloom_fake_tool")],
            name="prefix-collision",
        )
