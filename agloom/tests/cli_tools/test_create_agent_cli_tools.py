"""``create_agent(..., cli_tools=…)`` wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import tool

from agloom.cli_tools import CLI_TOOL_NAMES, CLI_TOOLS_SYSTEM_APPENDIX
from agloom.models import DEFAULT_SYSTEM_PROMPT
from agloom.prompts.core import ANSWER_CONTRACT_MARKER
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
    assert "write_file" in ibi
    assert "delete_file" in ibi
    assert "notebook_edit" in ibi
    assert agent.config.get("_cli_tools") is not None
    sp = agent.config["system_prompt"]
    assert isinstance(sp, str)
    assert "Bundled workspace tools" in sp
    assert DEFAULT_SYSTEM_PROMPT.strip() in sp
    assert ANSWER_CONTRACT_MARKER in sp
    assert CLI_TOOLS_SYSTEM_APPENDIX.strip() in sp


@pytest.mark.asyncio
async def test_cli_tools_appendix_omitted_when_builtins_fully_replaced_by_name() -> None:
    """If every built-in name is shadowed by user tools, do not claim bundled workspace tools."""
    from unittest.mock import patch

    from langchain_core.tools import StructuredTool

    builtin = StructuredTool.from_function(lambda: "b", name="read_file", description="built")
    user_tool = StructuredTool.from_function(lambda: "u", name="read_file", description="usr")

    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    with patch("agloom.cli_tools.get_cli_tools", return_value=[builtin]):
        agent = await create_agent(model=llm, name="shadow-read", cli_tools=True, tools=[user_tool])
    sp = agent.config["system_prompt"]
    assert DEFAULT_SYSTEM_PROMPT.strip() in sp
    assert ANSWER_CONTRACT_MARKER in sp
    assert "Bundled workspace tools" not in sp


@pytest.mark.asyncio
async def test_cli_tools_disabled_leaves_default_system_prompt() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    agent = await create_agent(model=llm, name="no-cli", cli_tools=None)
    sp = agent.config["system_prompt"]
    assert DEFAULT_SYSTEM_PROMPT.strip() in sp
    assert ANSWER_CONTRACT_MARKER in sp


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
async def test_cli_tools_require_approval_wildcard_when_callback() -> None:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock())
    cb = AsyncMock(return_value="continue")
    agent = await create_agent(
        model=llm,
        name="rq-full-hitl",
        cli_tools=True,
        user_callback=cb,
        require_tool_approval_for_cli_tools=True,
    )
    ibi = agent.config["interrupt_before_tools"]
    assert ibi and ibi[0] == "tools"


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
    assert "write_file" in ibi
    assert "edit_file" in ibi
