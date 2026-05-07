"""StructuredTool.invoke smoke tests — catch LangChain *args vs ``parts=[...]`` style mismatches.

LangGraph / StructuredTool often maps variadic Python parameters to a single JSON list field;
only explicit ``list[T]`` parameters align with that calling convention (see ``path_join``).
"""

from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool

from agloom_cli.tools.task_tracker import create_task_plan


@pytest.mark.asyncio
async def test_create_task_plan_structured_tool_accepts_steps_list() -> None:
    t = StructuredTool.from_function(
        coroutine=create_task_plan,
        name="create_task_plan",
        description="plan",
    )
    out = await t.ainvoke({"task": "Ship feature", "steps": ["Design", "Implement", "Test"]})
    assert "Ship feature" in out
    assert "Design" in out and "Implement" in out
