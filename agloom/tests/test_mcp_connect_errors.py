"""MCP connect diagnostics: ExceptionGroup unwrapping and transport fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agloom.mcp_support import (
    MCPServerConfig,
    _adapter_transport,
    _build_server_dict,
    _unwrap_exception,
    format_mcp_connect_error,
    load_mcp_capabilities,
)


def test_unwrap_exception_group_surfaces_sub_exception() -> None:
    inner = PermissionError("403 Forbidden")
    outer = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])
    assert _unwrap_exception(outer) is inner


def test_format_mcp_connect_error_includes_transport_url_and_root() -> None:
    cfg = MCPServerConfig(
        name="elastic-agent-builder",
        transport="sse",
        url="https://example.com/mcp",
    )
    inner = PermissionError("403 Forbidden")
    inner.status_code = 403  # type: ignore[attr-defined]
    group = ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)", [inner])
    text = format_mcp_connect_error(cfg, group, transport_used="sse")
    assert "server='elastic-agent-builder'" in text
    assert "transport=sse" in text
    assert "url=https://example.com/mcp" in text
    assert "403 Forbidden" in text
    assert "status=403" in text


def test_adapter_transport_maps_http_to_streamable_http() -> None:
    assert _adapter_transport("http") == "streamable_http"
    assert _adapter_transport("sse") == "sse"


def test_build_server_dict_normalizes_http_transport() -> None:
    cfg = MCPServerConfig(name="api", transport="http", url="http://localhost/mcp")
    d = _build_server_dict([cfg])
    assert d["api"]["transport"] == "streamable_http"


@pytest.mark.asyncio
async def test_load_mcp_capabilities_retries_sse_as_streamable_http() -> None:
    cfg = MCPServerConfig(name="remote", transport="sse", url="http://127.0.0.1/mcp")
    calls: list[str] = []

    class _FakeClient:
        def __init__(self, server_dict: dict) -> None:
            self._server_dict = server_dict

        async def get_tools(self, *, server_name: str):
            transport = self._server_dict[server_name]["transport"]
            calls.append(transport)
            if transport == "sse":
                raise ExceptionGroup(
                    "unhandled errors in a TaskGroup (1 sub-exception)",
                    [ConnectionError("connection refused")],
                )
            tool = MagicMock()
            tool.name = "demo_tool"
            return [tool]

        def session(self, name: str):
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.list_resources = AsyncMock(return_value=MagicMock(resources=[]))
            session.list_prompts = AsyncMock(return_value=MagicMock(prompts=[]))
            return session

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", _FakeClient):
        caps, _client, _holder = await load_mcp_capabilities([cfg])

    assert calls == ["sse", "streamable_http"]
    assert caps[0].last_error is None
    assert caps[0].transport_used == "streamable_http"
    assert len(caps[0].tools) == 1


@pytest.mark.asyncio
async def test_load_mcp_capabilities_reports_rich_error_after_retry() -> None:
    cfg = MCPServerConfig(name="bad", transport="sse", url="http://127.0.0.1/nope")

    class _FailClient:
        def __init__(self, server_dict: dict) -> None:
            self._server_dict = server_dict

        async def get_tools(self, *, server_name: str):
            raise ExceptionGroup(
                "unhandled errors in a TaskGroup (1 sub-exception)",
                [OSError(111, "Connection refused")],
            )

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", _FailClient):
        caps, _client, _holder = await load_mcp_capabilities([cfg])

    assert caps[0].last_error is not None
    assert "server='bad'" in caps[0].last_error
    assert "transport=streamable_http" in caps[0].last_error
    assert "Connection refused" in caps[0].last_error


@pytest.mark.asyncio
async def test_connect_mcp_servers_fails_when_server_returns_zero_tools() -> None:
    from agloom.mcp_support import MCPConnectionError, connect_mcp_servers

    cfg = MCPServerConfig(name="empty", transport="sse", url="http://127.0.0.1/mcp")
    agent: dict = {"tools": [], "name": "test-agent"}

    class _EmptyClient:
        def __init__(self, server_dict: dict) -> None:
            self._server_dict = server_dict

        async def get_tools(self, *, server_name: str):
            return []

        def session(self, name: str):
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.list_resources = AsyncMock(return_value=MagicMock(resources=[]))
            session.list_prompts = AsyncMock(return_value=MagicMock(prompts=[]))
            return session

    with patch("langchain_mcp_adapters.client.MultiServerMCPClient", _EmptyClient):
        with pytest.raises(MCPConnectionError, match="registered no callable tools"):
            await connect_mcp_servers([cfg], agent)

    assert agent.get("tools") == []
