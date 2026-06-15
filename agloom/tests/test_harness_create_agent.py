"""``create_agent(..., harness=True)`` wires progress + git tools to a real ProgressTracker."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.store.memory import InMemoryStore

from agloom.unified_agent import create_agent

_HARNESS_TOOL_NAMES = frozenset(
    {
        "git_status",
        "git_log",
        "git_commit",
        "git_checkpoint",
        "git_revert_hint",
        "bootstrap_progress",
        "save_progress",
        "update_task",
        "get_next_task",
        "add_task",
        "initialize_project",
    }
)


@pytest.mark.asyncio
async def test_harness_true_creates_agent_and_injects_tools() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    store = InMemoryStore()
    agent = await create_agent(model=llm, store=store, harness=True, name="harness-test")
    names = {t.name for t in agent.config["tools"]}
    assert names >= _HARNESS_TOOL_NAMES
    assert agent.config.get("_harness_enabled") is True
    assert agent.config.get("_progress_tracker") is not None


@pytest.mark.asyncio
async def test_harness_true_without_store_disables_harness() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    agent = await create_agent(model=llm, harness=True, name="no-store")
    names = {t.name for t in agent.config["tools"]}
    assert not (_HARNESS_TOOL_NAMES & names)
    assert agent.config.get("_harness_enabled") is False


@pytest.mark.asyncio
async def test_harness_async_tools_are_awaited_not_raw_coroutines() -> None:
    """Harness factories return async defs — must register with coroutine=, not func=."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    store = InMemoryStore()
    agent = await create_agent(model=llm, store=store, harness=True, name="harness-async")
    get_next = next(t for t in agent.config["tools"] if t.name == "get_next_task")
    git_status = next(t for t in agent.config["tools"] if t.name == "git_status")
    assert inspect.iscoroutinefunction(get_next.coroutine)
    assert inspect.iscoroutinefunction(git_status.coroutine)
    out = await get_next.ainvoke({})
    assert not inspect.iscoroutine(out)
    assert isinstance(out, str)
