"""Integration matrix: injected tools must be async-safe (no raw coroutine returns)."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import BaseTool
from langgraph.store.memory import InMemoryStore

from agloom.unified_agent import create_agent, normalize_tools

# Tools safe to invoke with {} or minimal args in CI (no network / git / destructive FS).
_SAFE_INVOKE: dict[str, dict] = {
    "get_next_task": {},
    "git_status": {},
    "git_revert_hint": {},
    "bootstrap_progress": {"goal": "test"},
    "save_progress": {"notes": "ci"},
    "list_mcp_servers": {},
    "write_todos": {"items_json": "[]"},
}

_SKIP_INVOKE = frozenset(
    {
        "git_commit",
        "git_checkpoint",
        "git_diff",
        "git_log",
        "initialize_project",
        "update_task",
        "add_task",
        "read_file",
        "write_file",
        "edit_file",
        "execute",
        "bash",
        "task",
        "save_memory",
        "recall_memory",
        "load_skill",
        "ask_user",
    }
)


def _assert_tool_async_safe(tool: BaseTool) -> None:
    """Async tools must expose coroutine=; sync tools expose func=."""
    if getattr(tool, "coroutine", None) is not None:
        assert inspect.iscoroutinefunction(tool.coroutine)
        return
    func = getattr(tool, "func", None)
    assert func is not None, f"{tool.name}: no func or coroutine"
    assert not inspect.iscoroutinefunction(func), f"{tool.name}: async func registered as sync"


@pytest.mark.asyncio
async def test_harness_tools_async_registration_matrix() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    store = InMemoryStore()
    agent = await create_agent(model=llm, store=store, harness=True, name="matrix-harness")
    harness_names = {
        "git_status",
        "git_log",
        "git_commit",
        "git_checkpoint",
        "git_diff",
        "git_revert_hint",
        "bootstrap_progress",
        "save_progress",
        "update_task",
        "get_next_task",
        "add_task",
        "initialize_project",
    }
    tools = [t for t in agent.config["tools"] if t.name in harness_names]
    assert len(tools) == len(harness_names)
    for tool in tools:
        _assert_tool_async_safe(tool)
        if tool.name in _SKIP_INVOKE:
            continue
        args = _SAFE_INVOKE.get(tool.name, {})
        out = await tool.ainvoke(args)
        assert not inspect.iscoroutine(out), f"{tool.name} returned unawaited coroutine"
        assert isinstance(out, str)


def test_normalize_tools_wraps_async_callable_with_coroutine() -> None:
    async def async_tool() -> str:
        return "done"

    wrapped = normalize_tools([async_tool])[0]
    _assert_tool_async_safe(wrapped)
    assert wrapped.name == "async_tool"
