"""``create_agent(..., cli_tools=…)`` wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import tool

from agloom.cli_tools import CLI_TOOL_NAMES
from agloom.unified_agent import create_agent


@pytest.mark.asyncio
async def test_cli_tools_adds_builtin_names() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    agent = await create_agent(model=llm, name="cli-tools", cli_tools=True)
    names = {t.name for t in agent.config["tools"]}
    assert names >= CLI_TOOL_NAMES
    ibi = agent.config["interrupt_before_tools"]
    assert "execute" in ibi
    assert "bash" in ibi
    assert "bash_background" in ibi
    assert agent.config.get("_cli_tools") is not None


@pytest.mark.asyncio
async def test_user_tool_overrides_cli_builtin() -> None:
    @tool
    def read_file() -> str:
        """USER_CLI_TOOLS_OVERRIDE_MARKER"""
        return "x"

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    agent = await create_agent(model=llm, tools=[read_file], name="override", cli_tools=True)
    by_name = {t.name: t for t in agent.config["tools"]}
    desc = (by_name["read_file"].description or "").lower()
    assert "user_cli_tools_override_marker" in desc


@pytest.mark.asyncio
async def test_cli_tools_task_tool_disabled(tmp_path: Path) -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    agent = await create_agent(
        model=llm,
        name="no-task-tool",
        cli_tools={
            "working_dir": str(tmp_path),
            "task_tool": False,
            "allow_shell": False,
            "allow_network": True,
            "sandbox": True,
        },
    )
    names = {t.name for t in agent.config["tools"]}
    assert "task" not in names


@pytest.mark.asyncio
async def test_cli_tools_no_shell_skips_execute_tool_and_interrupt() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    agent = await create_agent(
        model=llm,
        name="no-shell",
        cli_tools={"working_dir": ".", "allow_shell": False, "allow_network": True, "sandbox": True},
    )
    names = {t.name for t in agent.config["tools"]}
    assert "execute" not in names
    assert "bash_background" not in names
    ibi = agent.config["interrupt_before_tools"]
    assert "execute" not in ibi
    assert "bash_background" not in ibi
