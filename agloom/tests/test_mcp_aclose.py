"""Tests for ``aclose_mcp_client`` (MCP shutdown without context manager)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agloom.mcp_support import aclose_mcp_client


@pytest.mark.asyncio
async def test_aclose_prefers_aexit_when_available() -> None:
    client = MagicMock()
    client.__aexit__ = AsyncMock()
    await aclose_mcp_client(client, log_name="t")
    client.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_falls_back_to_aclose_after_notimplemented() -> None:
    client = MagicMock()
    client.__aexit__ = AsyncMock(side_effect=NotImplementedError())
    client.aclose = AsyncMock()
    await aclose_mcp_client(client, log_name="t")
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_aclose_sync_close() -> None:
    called: list[str] = []

    class _C:
        def close(self) -> None:
            called.append("close")

    await aclose_mcp_client(_C(), log_name="t")
    assert called == ["close"]


@pytest.mark.asyncio
async def test_aclose_none_is_noop() -> None:
    await aclose_mcp_client(None, log_name="t")
