"""MCP config merging — Super-Brain is always first for the CLI."""

from __future__ import annotations

import sys

from agloom_cli.mcp_loader import build_mcp_configs, superbrain_stdio_config


def test_superbrain_always_present() -> None:
    servers = build_mcp_configs({}, None)
    assert len(servers) >= 1
    assert servers[0].name == "agsuperbrain"
    assert servers[0].transport == "stdio"
    assert servers[0].command == sys.executable
    assert servers[0].args == ["-m", "agsuperbrain"]


def test_server_list_after_superbrain() -> None:
    cfg = {
        "mcp": {
            "server_list": [
                {
                    "name": "demo",
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "@scope/server"],
                }
            ]
        }
    }
    servers = build_mcp_configs(cfg, None)
    assert len(servers) == 2
    assert servers[0].name == "agsuperbrain"
    assert servers[1].name == "demo"


def test_server_list_can_replace_superbrain_by_name() -> None:
    cfg = {
        "mcp": {
            "server_list": [
                {
                    "name": "agsuperbrain",
                    "transport": "stdio",
                    "command": "custom-mcp",
                    "args": ["--stdio"],
                }
            ]
        }
    }
    servers = build_mcp_configs(cfg, None)
    assert len(servers) == 1
    assert servers[0].command == "custom-mcp"
    assert servers[0].args == ["--stdio"]


def test_legacy_skips_duplicate_superbrain_argv() -> None:
    sb = superbrain_stdio_config({})
    cfg: dict = {"mcp": {"servers": f"{sb.command} -m agsuperbrain,node script.js"}}
    servers = build_mcp_configs(cfg, None)
    assert len(servers) == 2
    assert servers[0].name == "agsuperbrain"
    assert servers[1].name == "node"


def test_cli_override_legacy_string() -> None:
    cfg = {"mcp": {"servers": "echo hello"}}
    servers = build_mcp_configs(cfg, "python -c pass")
    assert servers[0].name == "agsuperbrain"
    assert servers[1].name == "python"
    assert servers[1].args == ["-c", "pass"]
