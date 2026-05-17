"""LLM-only workers must emit ``llm_call`` usage exactly once per model turn."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from agloom.models import ResolvedWorkerConfig
from agloom.worker import _run_llm_only
from agloom.wire_tokens import emitted_usage, reset_wire_emitted_usage


class _StreamingLLM:
    def with_config(self, **_kw: Any) -> _StreamingLLM:
        return self

    async def astream(self, _messages: Any) -> Any:
        yield AIMessage(
            content="answer",
            usage_metadata={"input_tokens": 11, "output_tokens": 4, "total_tokens": 15},
        )


@pytest.mark.asyncio
async def test_run_llm_only_emits_llm_call_once_on_streaming_path() -> None:
    q: asyncio.Queue = asyncio.Queue()
    invoke_config: dict = {"_event_queue": q, "llm": _StreamingLLM()}
    reset_wire_emitted_usage(invoke_config)

    config = ResolvedWorkerConfig(
        worker_id="w1",
        task="Say hi",
        system_prompt="You are helpful.",
        tools=[],
        max_retries=0,
        llm_timeout=30.0,
    )

    result = await _run_llm_only(config, _StreamingLLM(), invoke_config)
    assert result.signal.value == "SUCCESS"

    llm_events: list = []
    while not q.empty():
        evt = q.get_nowait()
        if evt.type == "llm_call":
            llm_events.append(evt)

    assert len(llm_events) == 1
    assert llm_events[0].data["usage"]["input_tokens"] == 11
    assert emitted_usage(invoke_config)["input_tokens"] == 11
