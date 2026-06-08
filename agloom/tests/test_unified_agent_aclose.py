"""Minimal lifecycle tests for ``UnifiedAgent`` (MCP cleanup)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agloom.unified_agent import UnifiedAgent


@pytest.mark.asyncio
async def test_unified_agent_aclose_calls_mcp_shutdown() -> None:
    mcp = MagicMock()
    mcp.__aexit__ = AsyncMock(side_effect=NotImplementedError())
    mcp.aclose = AsyncMock()

    agent = UnifiedAgent(
        {
            "name": "u-test",
            "tools": [],
            "_mcp_client": mcp,
            "_mcp_session_attempted": True,
            "_mcp_connected": True,
        }
    )
    await agent.aclose()

    assert agent.config.get("_mcp_client") is None
    assert agent.config.get("_mcp_connected") is False
    assert agent.config.get("_mcp_session_attempted") is False
    mcp.aclose.assert_awaited_once()


def test_unified_agent_resolve_ids_memory_namespace() -> None:
    agent = UnifiedAgent({"name": "demo", "tools": [], "user_id": "ignored_when_explicit_thread"})
    tid, ns, inv = agent.resolve_ids(thread_id="thread-9", user_id="u42", lt_namespace=None)
    assert tid == "thread-9"
    assert ns == ("demo", "u42")
    assert inv["configurable"]["memory_namespace"] == ns
    assert inv["configurable"]["thread_id"] == tid
