"""C6: MCP timeout wired in client dict."""

from agloom.src.mcp_support import MCPServerConfig


def test_mcp_timeout_in_client_dict():
    cfg = MCPServerConfig(name="s", transport="stdio", command="echo", timeout=42.0)
    d = cfg.to_client_dict()
    assert d.get("timeout") == 42.0
