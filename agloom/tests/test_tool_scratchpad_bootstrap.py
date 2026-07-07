"""Scratchpad bootstrap for MCP-only, memory, and harness tool shapes."""

from __future__ import annotations

from langchain_core.tools import BaseTool, StructuredTool

from agloom.context.tool_scratchpad import (
    attach_tool_scratchpad,
    ensure_tool_scratchpad_config,
    is_recall_tool_name,
)


def _dummy_tool() -> StructuredTool:
    def ping() -> str:
        """ping"""
        return "ok"

    return StructuredTool.from_function(ping, name="ping")


def test_attach_tool_scratchpad_adds_recall_once():
    tools: list[BaseTool] = [_dummy_tool()]
    pad, out = attach_tool_scratchpad(tools, agent_key="agent-a")
    assert pad is not None
    assert len(out) == 2
    assert is_recall_tool_name(out[-1].name)


def test_ensure_tool_scratchpad_config_idempotent():
    tools: list[BaseTool] = [_dummy_tool()]
    pad, tools = attach_tool_scratchpad(tools, agent_key="agent-b")
    cfg: dict = {"name": "agent-b", "tools": tools, "_tool_scratchpad": pad}
    assert ensure_tool_scratchpad_config(cfg) is False
    assert sum(1 for t in cfg["tools"] if is_recall_tool_name(t.name)) == 1


def test_ensure_tool_scratchpad_config_from_empty_pad():
    tools: list[BaseTool] = [_dummy_tool()]
    cfg: dict = {"name": "agent-c", "tools": tools}
    assert ensure_tool_scratchpad_config(cfg) is True
    assert cfg.get("_tool_scratchpad") is not None
    assert any(is_recall_tool_name(t.name) for t in cfg["tools"])


def test_ensure_tool_scratchpad_skips_toolless_agent():
    cfg: dict = {"name": "agent-d", "tools": []}
    assert ensure_tool_scratchpad_config(cfg) is False
    assert cfg.get("_tool_scratchpad") is None
