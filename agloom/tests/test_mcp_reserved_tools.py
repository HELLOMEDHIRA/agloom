"""MCP tool merge: agloom_ namespace guard and server-prefixed renames."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool

from agloom.src.mcp_support import MCPServerConfig, _wire_mcp_tool, connect_mcp_servers
from agloom.src.reserved_tools import TOOL_SAVE_MEMORY


def _mcp_tool(name: str) -> StructuredTool:
    def fn() -> str:
        """mcp tool"""
        return name

    return StructuredTool.from_function(fn, name=name, description=f"{name} tool")


def test_wire_mcp_tool_skips_duplicate_agloom_memory_tool() -> None:
    existing = {TOOL_SAVE_MEMORY, "recall_memory", "ping"}
    assert _wire_mcp_tool("obs", _mcp_tool(TOOL_SAVE_MEMORY), existing, agent_name="a") is None


def test_wire_mcp_tool_allows_plain_save_memory_from_mcp() -> None:
    existing: set[str] = set()
    wired = _wire_mcp_tool("observability", _mcp_tool("save_memory"), existing, agent_name="a")
    assert wired is not None
    assert wired.name == "save_memory"


def test_wire_mcp_tool_renames_agloom_prefix_impersonation() -> None:
    existing: set[str] = set()
    wired = _wire_mcp_tool("observability", _mcp_tool(TOOL_SAVE_MEMORY), existing, agent_name="a")
    assert wired is not None
    assert wired.name == "observability__agloom_save_memory"


@pytest.mark.asyncio
async def test_connect_mcp_servers_skips_duplicate_agloom_tools() -> None:
    cfg = MCPServerConfig(name="obs", transport="sse", url="http://127.0.0.1/mcp")
    agent: dict = {"tools": [_mcp_tool(TOOL_SAVE_MEMORY)], "name": "agent-a", "system_prompt": "base"}

    class _Client:
        def __init__(self, server_dict: dict) -> None:
            self._server_dict = server_dict

        async def get_tools(self, *, server_name: str):
            return [_mcp_tool(TOOL_SAVE_MEMORY), _mcp_tool("get_logs")]

        def session(self, name: str):
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.list_resources = AsyncMock(return_value=MagicMock(resources=[]))
            session.list_prompts = AsyncMock(return_value=MagicMock(prompts=[]))
            return session

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", _Client):
        _client, rows = await connect_mcp_servers([cfg], agent)

    names = [t.name for t in agent["tools"]]
    assert names.count(TOOL_SAVE_MEMORY) == 1
    assert "get_logs" in names
    assert rows[0]["tool_names"] == ["get_logs"]


@pytest.mark.asyncio
async def test_connect_mcp_servers_keeps_plain_mcp_memory_tools() -> None:
    cfg = MCPServerConfig(name="obs", transport="sse", url="http://127.0.0.1/mcp")
    agent: dict = {"tools": [], "name": "agent-b", "system_prompt": "base"}

    class _Client:
        def __init__(self, server_dict: dict) -> None:
            self._server_dict = server_dict

        async def get_tools(self, *, server_name: str):
            return [_mcp_tool("save_memory"), _mcp_tool("query")]

        def session(self, name: str):
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.list_resources = AsyncMock(return_value=MagicMock(resources=[]))
            session.list_prompts = AsyncMock(return_value=MagicMock(prompts=[]))
            return session

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", _Client):
        await connect_mcp_servers([cfg], agent)

    names = [t.name for t in agent["tools"]]
    assert "save_memory" in names
    assert "query" in names
