"""Tests for wire token emission bookkeeping."""

from __future__ import annotations

import asyncio

import pytest

from agloom.models import AgentStep, StepType, _make_step
from agloom.wire_tokens import (
    accumulate_stream_usage,
    emit_llm_call_usage,
    emit_remaining_token_usage,
    emit_usage_from_llm_response,
    emitted_usage,
    finalize_stream_usage,
    record_emitted_usage,
    reset_wire_emitted_usage,
    usage_remainder,
)


@pytest.mark.asyncio
async def test_emit_llm_call_records_emitted() -> None:
    q: asyncio.Queue = asyncio.Queue()
    cfg: dict = {"_event_queue": q}
    reset_wire_emitted_usage(cfg)
    await emit_llm_call_usage(cfg, {"input_tokens": 10, "output_tokens": 5}, phase="test")
    evt = await asyncio.wait_for(q.get(), timeout=1.0)
    assert evt.type == "llm_call"
    assert evt.data["usage"]["input_tokens"] == 10
    assert emitted_usage(cfg)["input_tokens"] == 10


@pytest.mark.asyncio
async def test_remainder_skips_already_emitted() -> None:
    q: asyncio.Queue = asyncio.Queue()
    cfg: dict = {"_event_queue": q}
    reset_wire_emitted_usage(cfg)
    record_emitted_usage(cfg, {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140})
    await emit_remaining_token_usage(
        cfg,
        {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140},
        phase="REACT",
    )
    assert q.empty()


def test_accumulate_stream_usage_sums_deltas_when_totals_decrease() -> None:
    class Chunk:
        def __init__(self, meta: dict) -> None:
            self.usage_metadata = meta

    acc: dict[str, int] = {}
    accumulate_stream_usage(acc, Chunk({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}))
    accumulate_stream_usage(acc, Chunk({"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}))
    assert finalize_stream_usage(acc) == {
        "input_tokens": 13,
        "output_tokens": 7,
        "total_tokens": 20,
    }


def test_accumulate_stream_usage_bedrock_label_sums_deltas() -> None:
    class Chunk:
        model_name = "anthropic.claude-3-bedrock"

        def __init__(self, meta: dict) -> None:
            self.usage_metadata = meta

    acc: dict[str, int] = {}
    accumulate_stream_usage(acc, Chunk({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}))
    accumulate_stream_usage(acc, Chunk({"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}))
    assert finalize_stream_usage(acc) == {
        "input_tokens": 13,
        "output_tokens": 7,
        "total_tokens": 20,
    }


def test_accumulate_stream_usage_monotonic_max() -> None:
    class Chunk:
        def __init__(self, meta: dict) -> None:
            self.usage_metadata = meta

    acc: dict[str, int] = {}
    accumulate_stream_usage(acc, Chunk({"input_tokens": 100, "output_tokens": 0}))
    accumulate_stream_usage(acc, Chunk({"input_tokens": 100, "output_tokens": 42}))
    assert finalize_stream_usage(acc) == {
        "input_tokens": 100,
        "output_tokens": 42,
        "total_tokens": 142,
    }


@pytest.mark.asyncio
async def test_emit_usage_prefers_stream_accumulated_over_empty_last_chunk() -> None:
    q: asyncio.Queue = asyncio.Queue()
    cfg: dict = {"_event_queue": q}
    reset_wire_emitted_usage(cfg)
    stream_acc = {"input_tokens": 9, "output_tokens": 3, "total_tokens": 0}

    class EmptyLast:
        usage_metadata = None

    await emit_usage_from_llm_response(
        cfg,
        EmptyLast(),
        phase="test",
        stream_accumulated=stream_acc,
    )
    evt = q.get_nowait()
    assert evt.type == "llm_call"
    assert evt.data["usage"]["input_tokens"] == 9
    assert evt.data["usage"]["output_tokens"] == 3
    assert evt.data["usage"]["total_tokens"] == 12


def test_usage_remainder_partial() -> None:
    total = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
    emitted = {"input_tokens": 80, "output_tokens": 50, "total_tokens": 130}
    rem = usage_remainder(total, emitted)
    assert rem["input_tokens"] == 20
    assert rem["output_tokens"] == 0


@pytest.mark.asyncio
async def test_emit_llm_call_from_step() -> None:
    q: asyncio.Queue = asyncio.Queue()
    cfg: dict = {"_event_queue": q}
    reset_wire_emitted_usage(cfg)
    step = _make_step(
        StepType.LLM_CALL,
        "swarm_synthesis",
        usage={"input_tokens": 3, "output_tokens": 7},
        phase="swarm_synthesis",
    )
    from agloom.wire_tokens import emit_llm_call_from_step

    await emit_llm_call_from_step(cfg, step)
    assert step.metadata.get("_wire_emitted") is True
    evt = await q.get()
    assert evt.type == "llm_call"
