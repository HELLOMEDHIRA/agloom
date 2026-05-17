"""Tool resolution warnings when required_tools are absent from the registry."""

from __future__ import annotations

import asyncio

import pytest

from agloom.models import QueryAnalysis, PatternType, SubTask
from agloom.patterns._resolve import resolve_worker_configs


def _analysis() -> QueryAnalysis:
    return QueryAnalysis(
        pattern=PatternType.SUPERVISOR,
        complexity=5,
        reasoning="test",
        subtasks=[
            SubTask(
                worker_id="w1",
                task="do thing",
                required_tools=["missing_tool", "also_missing"],
            ),
        ],
    )


def test_resolve_records_missing_tools_on_config() -> None:
    agent = {"tools": [], "system_prompt": "sys", "llm_timeout": 30.0}
    configs = resolve_worker_configs(agent, _analysis())
    assert len(configs) == 1
    assert configs[0].missing_tools == ["missing_tool", "also_missing"]
    assert configs[0].tools == []


@pytest.mark.asyncio
async def test_resolve_enqueues_thinking_warning_when_queue_present() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    agent = {"tools": [], "system_prompt": "sys", "llm_timeout": 30.0, "_event_queue": queue}
    resolve_worker_configs(agent, _analysis())
    evt = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert evt.type == "thinking"
    assert "missing_tool" in evt.data.get("detail", "")
