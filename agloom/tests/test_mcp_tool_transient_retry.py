"""Per-call transient-transport retry for MCP tools (bounded, in-place re-dial).

A single flaky connect on one stateless MCP read must be re-dialed at the tool-call granularity —
NOT bubbled up to the stream handler (which would compact context or replay the whole REACT turn).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool

from agloom.src.mcp_support import MCPServerConfig, _wire_mcp_tool, connect_mcp_servers


class RemoteProtocolError(Exception):
    """Stand-in with the same type name httpx uses (matched by the transient detector)."""


def _flaky_tool(calls: dict[str, int], *, fail_times: int, exc: Exception) -> StructuredTool:
    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise exc
        return "logs-ok"

    return StructuredTool.from_function(coroutine=flaky, name="get_logs", description="reads logs")


@pytest.mark.asyncio
async def test_mcp_tool_retries_transient_transport_error_in_place() -> None:
    calls = {"n": 0}
    tool = _flaky_tool(
        calls,
        fail_times=1,
        exc=RemoteProtocolError("Server disconnected without sending a response."),
    )

    wired = _wire_mcp_tool("obs", tool, set(), agent_name="a", mcp_tool_max_retries=2)
    assert wired is not None

    # The blip is absorbed here: ainvoke succeeds, so the stream handler never sees a transport
    # error and no compaction / replay is triggered.
    result = await wired.ainvoke({})
    assert result == "logs-ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_mcp_tool_retry_disabled_when_zero() -> None:
    calls = {"n": 0}
    tool = _flaky_tool(
        calls,
        fail_times=1,
        exc=RemoteProtocolError("Server disconnected without sending a response."),
    )

    wired = _wire_mcp_tool("obs", tool, set(), agent_name="a", mcp_tool_max_retries=0)
    assert wired is not None

    with pytest.raises(Exception, match="Server disconnected"):
        await wired.ainvoke({})
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_mcp_tool_does_not_retry_non_transient_error() -> None:
    calls = {"n": 0}
    tool = _flaky_tool(calls, fail_times=1, exc=ValueError("bad argument"))

    wired = _wire_mcp_tool("obs", tool, set(), agent_name="a", mcp_tool_max_retries=3)
    assert wired is not None

    with pytest.raises(ValueError, match="bad argument"):
        await wired.ainvoke({})
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_mcp_tool_gives_up_after_max_retries() -> None:
    calls = {"n": 0}
    tool = _flaky_tool(
        calls,
        fail_times=99,
        exc=RemoteProtocolError("Server disconnected without sending a response."),
    )

    wired = _wire_mcp_tool("obs", tool, set(), agent_name="a", mcp_tool_max_retries=2)
    assert wired is not None

    with pytest.raises(Exception, match="Server disconnected"):
        await wired.ainvoke({})
    # first attempt + 2 retries
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_connect_mcp_servers_wires_transient_retry() -> None:
    cfg = MCPServerConfig(name="obs", transport="sse", url="http://127.0.0.1/mcp")
    agent: dict = {
        "tools": [],
        "name": "agent-a",
        "system_prompt": "base",
        "mcp_tool_max_retries": 2,
    }
    calls = {"n": 0}
    flaky = _flaky_tool(
        calls,
        fail_times=1,
        exc=RemoteProtocolError("Server disconnected without sending a response."),
    )

    class _Client:
        def __init__(self, server_dict: dict) -> None:
            self._server_dict = server_dict

        async def get_tools(self, *, server_name: str):
            return [flaky]

        def session(self, name: str):
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.list_resources = AsyncMock(return_value=MagicMock(resources=[]))
            session.list_prompts = AsyncMock(return_value=MagicMock(prompts=[]))
            return session

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", _Client):
        await connect_mcp_servers([cfg], agent)

    wired = next(t for t in agent["tools"] if t.name == "get_logs")
    result = await wired.ainvoke({})
    assert result == "logs-ok"
    assert calls["n"] == 2
