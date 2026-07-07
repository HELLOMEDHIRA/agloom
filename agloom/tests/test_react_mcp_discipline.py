"""MCP tool discipline prompt appendix."""

from __future__ import annotations

from agloom.patterns.react import MCP_TOOL_DISCIPLINE, _react_system_prompt


def test_mcp_discipline_appended_when_mcp_servers_configured():
    agent = {"system_prompt": "You are helpful.", "_mcp_servers": [{"name": "obs"}]}
    prompt = _react_system_prompt(agent)
    assert MCP_TOOL_DISCIPLINE.strip() in prompt
    assert "limit≤100" in prompt or "limit" in prompt


def test_mcp_discipline_omitted_without_mcp():
    agent = {"system_prompt": "You are helpful."}
    prompt = _react_system_prompt(agent)
    assert "=== MCP / EXTERNAL TOOL LIMITS" not in prompt
