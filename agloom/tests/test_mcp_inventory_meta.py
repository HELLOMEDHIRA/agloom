"""MCP inventory formatting and list_mcp_servers meta tool."""

from __future__ import annotations

import pytest

from agloom.mcp_support import format_mcp_inventory_text, mcp_configured_server_names


def test_format_mcp_inventory_text_from_rows() -> None:
    text = format_mcp_inventory_text(
        configured_names=["agsuperbrain"],
        server_rows=[
            {
                "name": "agsuperbrain",
                "ok": True,
                "tool_catalog": [
                    {"name": "search_code", "description": "Semantic search."},
                ],
            }
        ],
    )
    assert "agsuperbrain: connected" in text
    assert "search_code — Semantic search." in text
    assert "Kuzu" not in text


def test_mcp_configured_server_names() -> None:
    class _Srv:
        name = "demo"

    names = mcp_configured_server_names({"_mcp_servers": [_Srv()]})
    assert names == ["demo"]


@pytest.mark.asyncio
async def test_list_mcp_servers_meta_tool_uses_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from agloom.cli_tools.meta import make_meta_tools
    from agloom.runtime.invocation_context import attach_invocation_context, reset_invocation_context

    config: dict = {
        "_mcp_servers": [],
        "_mcp_server_rows": [
            {
                "name": "x",
                "ok": True,
                "tool_catalog": [{"name": "t1", "description": "does one thing"}],
            }
        ],
    }
    tokens = attach_invocation_context(None, None, config)
    try:
        tools = make_meta_tools()
        list_tool = next(t for t in tools if getattr(t, "name", None) == "list_mcp_servers")
        out = await list_tool.ainvoke({})
        assert "t1 — does one thing" in str(out)
    finally:
        reset_invocation_context(tokens)
