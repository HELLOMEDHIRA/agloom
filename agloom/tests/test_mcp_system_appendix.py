"""MCP system-prompt appendix after connect."""

from __future__ import annotations

from agloom.mcp_support import (
    MCP_SYSTEM_APPENDIX_MARKER,
    append_mcp_system_appendix_to_agent,
    build_mcp_system_appendix,
)


def test_build_mcp_system_appendix_lists_tools_with_descriptions() -> None:
    rows = [
        {
            "name": "agsuperbrain",
            "ok": True,
            "tool_count": 2,
            "tool_names": ["search_code", "read_graph"],
            "tool_catalog": [
                {"name": "search_code", "description": "Semantic search over the repository."},
                {"name": "read_graph", "description": "Read dependency graph nodes."},
            ],
            "tool_names_truncated": False,
        }
    ]
    text = build_mcp_system_appendix(rows, mcp_prompts={"agsuperbrain": ["review"]})
    assert MCP_SYSTEM_APPENDIX_MARKER in text
    assert "**agsuperbrain**" in text
    assert "`search_code` — Semantic search over the repository." in text
    assert "get_prompt_agsuperbrain" in text


def test_append_mcp_system_appendix_to_agent_idempotent() -> None:
    agent: dict = {"system_prompt": "Base persona.\n"}
    rows = [{"name": "demo", "ok": True, "tool_names": ["t1"], "tool_names_truncated": False}]
    append_mcp_system_appendix_to_agent(agent, rows)
    once = agent["system_prompt"]
    assert MCP_SYSTEM_APPENDIX_MARKER in once
    append_mcp_system_appendix_to_agent(agent, rows)
    assert agent["system_prompt"] == once


def test_append_skips_callable_system_prompt() -> None:
    agent: dict = {"system_prompt": lambda: "nope"}
    append_mcp_system_appendix_to_agent(agent, [{"name": "x", "ok": True, "tool_names": []}])
    assert callable(agent["system_prompt"])
