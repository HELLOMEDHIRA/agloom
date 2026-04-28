"""Build ``MCPServerConfig`` lists from agloom YAML and CLI overrides.

The CLI always attaches Super-Brain (``agsuperbrain``) over stdio for a local graph index and tools;
``mcp.superbrain`` in config can override name, command, and args.
"""

from __future__ import annotations

import os
import shlex
import sys
from typing import Any

from agloom.mcp_support import MCPServerConfig


def superbrain_stdio_config(mcp: dict[str, Any] | None = None) -> MCPServerConfig:
    """Stdio MCP server for Super-Brain (override bits in ``mcp.superbrain``)."""
    mcp = mcp or {}
    sb = mcp.get("superbrain") or {}
    name = str(sb.get("name") or "agsuperbrain")
    cmd = str(sb.get("command") or sys.executable)
    args = sb.get("args")
    if args is None:
        args = ["-m", "agsuperbrain"]
    elif isinstance(args, str):
        args = shlex.split(args, posix=os.name != "nt")
    else:
        args = list(args)
    return MCPServerConfig(name=name, transport="stdio", command=cmd, args=args)


def _split_legacy_segment(segment: str, index: int) -> MCPServerConfig:
    """Parse one comma-separated MCP entry into a stdio server."""
    seg = segment.strip()
    if not seg:
        raise ValueError("empty segment")
    posix = os.name != "nt"
    try:
        parts = shlex.split(seg, posix=posix)
    except ValueError:
        parts = [seg]
    if not parts:
        raise ValueError("no argv")
    command, args = parts[0], parts[1:]
    base = os.path.basename(command.replace("\\", "/"))
    name = base.removesuffix(".exe") or f"mcp{index}"
    return MCPServerConfig(name=name, transport="stdio", command=command, args=args)


def _same_stdio_argv(cfg: MCPServerConfig, command: str, args: list[str]) -> bool:
    return cfg.transport == "stdio" and cfg.command == command and list(cfg.args) == list(args)


def build_mcp_configs(cfg: dict[str, Any], cli_mcp_override: str | None) -> list[MCPServerConfig]:
    """Build MCP server list: **Super-Brain first** (required), then ``server_list``, then legacy ``servers`` / ``--mcp``.

    An entry in ``mcp.server_list`` with the same ``name`` as the Super-Brain server (default ``agsuperbrain``)
    replaces the auto-generated Super-Brain config for that slot.
    """
    mcp = cfg.get("mcp") or {}
    sb_default = superbrain_stdio_config(mcp)
    sb_name = sb_default.name

    seen: set[str] = set()
    out: list[MCPServerConfig] = []

    explicit: list[MCPServerConfig] = []
    for raw in mcp.get("server_list") or []:
        if not isinstance(raw, dict):
            continue
        explicit.append(MCPServerConfig.model_validate(raw))

    user_sb = next((c for c in explicit if c.name == sb_name), None)
    if user_sb is not None:
        out.append(user_sb)
        seen.add(user_sb.name)
        for c in explicit:
            if c.name == sb_name:
                continue
            if c.name in seen:
                continue
            out.append(c)
            seen.add(c.name)
    else:
        out.append(sb_default)
        seen.add(sb_name)
        for c in explicit:
            if c.name in seen:
                continue
            out.append(c)
            seen.add(c.name)

    legacy_src = cli_mcp_override if cli_mcp_override is not None else mcp.get("servers", "")
    if isinstance(legacy_src, str) and legacy_src.strip():
        for i, segment in enumerate(legacy_src.split(",")):
            seg = segment.strip()
            if not seg:
                continue
            try:
                c = _split_legacy_segment(seg, i)
            except ValueError:
                continue
            if c.name in seen:
                continue
            if c.command is not None and _same_stdio_argv(sb_default, c.command, c.args):
                continue
            out.append(c)
            seen.add(c.name)

    return out
