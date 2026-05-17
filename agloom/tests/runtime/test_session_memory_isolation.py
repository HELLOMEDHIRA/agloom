"""Per-AGP-session memory isolation for runtime transports."""

from __future__ import annotations

import argparse
from argparse import Namespace

import pytest
from langgraph.store.memory import InMemoryStore

from agloom.memory.session import SessionMemory
from agloom.runtime.session_memory import open_isolated_session_memory


def _args(**kw: object) -> Namespace:
    base = argparse.Namespace(
        memory_type="in-memory",
        session_max_turns=10,
        auto_summarize=False,
    )
    for k, v in kw.items():
        setattr(base, k, v)
    return base


@pytest.mark.asyncio
async def test_open_isolated_session_memory_uses_distinct_stores_per_session() -> None:
    a, _ = await open_isolated_session_memory(_args(), agp_session_id="ws_alpha")
    b, _ = await open_isolated_session_memory(_args(), agp_session_id="ws_beta")
    assert a is not None and b is not None
    assert a.store is not b.store
    assert a.agp_session_key != b.agp_session_key


@pytest.mark.asyncio
async def test_isolated_sessions_do_not_share_turn_data() -> None:
    store_a = InMemoryStore()
    store_b = InMemoryStore()
    sm_a = SessionMemory(store=store_a, max_turns=5, auto_summarize=False, agp_session_key="alpha")
    sm_b = SessionMemory(store=store_b, max_turns=5, auto_summarize=False, agp_session_key="beta")
    thread = "t1"

    await sm_a.aadd_turn(thread, "q1", "a1")
    await sm_b.aadd_turn(thread, "q2", "a2")

    ctx_a = await sm_a.aformat_context(thread, last_n=10)
    ctx_b = await sm_b.aformat_context(thread, last_n=10)
    assert "q1" in ctx_a and "q2" not in ctx_a
    assert "q2" in ctx_b and "q1" not in ctx_b

    # Same physical store but different agp_session_key must not collide.
    shared = InMemoryStore()
    sm_x = SessionMemory(store=shared, max_turns=5, auto_summarize=False, agp_session_key="x")
    sm_y = SessionMemory(store=shared, max_turns=5, auto_summarize=False, agp_session_key="y")
    await sm_x.aadd_turn(thread, "only-x", "ax")
    await sm_y.aadd_turn(thread, "only-y", "ay")
    assert "only-x" in await sm_x.aformat_context(thread, last_n=10)
    assert "only-y" in await sm_y.aformat_context(thread, last_n=10)
    assert "only-x" not in await sm_y.aformat_context(thread, last_n=10)
