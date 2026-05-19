"""Session memory and long-term store (no LLM)."""

from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from agloom.memory import (
    LongTermStore,
    SessionMemory,
    build_memory_context,
    create_memory_tools,
)


def test_session_memory_add_turn_and_format() -> None:
    sm = SessionMemory(store=InMemoryStore(), max_turns=5)
    sm.add_turn("t1", "Hello", "Hi there", "DIRECT")
    ctx = sm.format_context("t1")
    assert "Hello" in ctx
    assert "Hi there" in ctx


def test_session_memory_max_turns_eviction() -> None:
    sm = SessionMemory(store=InMemoryStore(), max_turns=2)
    sm.add_turn("t1", "q1", "a1")
    sm.add_turn("t1", "q2", "a2")
    sm.add_turn("t1", "q3", "a3")
    ctx = sm.format_context("t1", last_n=10)
    assert "q1" not in ctx
    assert "q3" in ctx


def test_session_memory_thread_isolation() -> None:
    sm = SessionMemory(store=InMemoryStore())
    sm.add_turn("t1", "q1", "a1")
    sm.add_turn("t2", "q2", "a2")
    c1 = sm.format_context("t1")
    c2 = sm.format_context("t2")
    assert "q1" in c1
    assert "q2" not in c1
    assert "q2" in c2


@pytest.mark.asyncio
async def test_session_memory_apop_last_turn() -> None:
    sm = SessionMemory(store=InMemoryStore())
    await sm.aadd_turn("t1", "q1", "a1")
    await sm.aadd_turn("t1", "q2", "a2")
    n = await sm.apop_last_turn("t1")
    assert n == 1
    ctx = await sm.aformat_context("t1", last_n=10)
    assert "q2" not in ctx
    assert "q1" in ctx
    assert await sm.apop_last_turn("t1") == 0
    assert await sm.apop_last_turn("t1") is None


@pytest.mark.asyncio
async def test_session_memory_on_turns_async() -> None:
    hooks: list[tuple[str, list]] = []
    sm = SessionMemory(store=InMemoryStore(), max_turns=10, auto_summarize=False)

    async def cb(tid: str, turns: list) -> None:
        hooks.append((tid, [dict(x) for x in turns]))

    sm.on_turns_async = cb
    await sm.aadd_turn("t1", "a", "b")
    assert len(hooks) == 1
    assert hooks[0][0] == "t1"
    assert hooks[0][1][-1]["q"] == "a"
    await sm.apop_last_turn("t1")
    assert len(hooks) == 2
    assert hooks[1][1] == []


@pytest.mark.asyncio
async def test_session_memory_summarize_at_max_tokens_budget() -> None:
    class FakeSumm:
        async def ainvoke(self, messages):
            class R:
                content = "rolled-up summary body"

            return R()

    sm = SessionMemory(
        store=InMemoryStore(),
        max_turns=50,
        auto_summarize=True,
        summarize_threshold=10**9,
        summarize_max_tokens_budget=500,
        summarizer_model=FakeSumm(),
    )
    await sm.aadd_turn("t1", "m1", "r1")
    await sm.aadd_turn("t1", "m2", "r2")
    await sm.aadd_turn("t1", "m3", "r3")
    await sm.aadd_turn("t1", "x" * 4000, "y" * 4000)
    ctx = await sm.aformat_context("t1", last_n=20)
    assert "rolled-up summary body" in ctx or "Previous conversation summary" in ctx


@pytest.mark.asyncio
async def test_session_memory_async() -> None:
    sm = SessionMemory(store=InMemoryStore())
    await sm.aadd_turn("t1", "async_q", "async_a")
    ctx = await sm.aformat_context("t1")
    assert "async_q" in ctx


def test_long_term_store_sync() -> None:
    lts = LongTermStore(store=InMemoryStore())
    lts.save(("ns",), "fact 1", topic="test")
    results = lts.search(("ns",), "fact")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_long_term_store_async() -> None:
    lts = LongTermStore(store=InMemoryStore())
    await lts.asave(("ns",), "async fact", topic="async")
    results = await lts.asearch(("ns",), "async")
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_long_term_namespace_isolation() -> None:
    lts = LongTermStore(store=InMemoryStore())
    await lts.asave(("a",), "fact for a")
    await lts.asave(("b",), "fact for b")
    ra = await lts.asearch(("a",), "fact")
    rb = await lts.asearch(("b",), "fact")
    a_vals = [getattr(r, "value", {}).get("memory", "") for r in ra]
    b_vals = [getattr(r, "value", {}).get("memory", "") for r in rb]
    assert any("a" in v for v in a_vals)
    assert any("b" in v for v in b_vals)


@pytest.mark.asyncio
async def test_long_term_skill_mode() -> None:
    lts = LongTermStore(store=InMemoryStore())
    k = await lts.asave(("skills",), key="my-skill", value="index text", metadata={"body": "skill body"})
    assert k == "my-skill"
    item = await lts.aget(("skills",), "my-skill")
    assert item is not None
    assert item.value.get("body") == "skill body"


@pytest.mark.asyncio
async def test_long_term_delete() -> None:
    lts = LongTermStore(store=InMemoryStore())
    await lts.asave(("ns",), key="k1", value="v1")
    await lts.adelete(("ns",), "k1")
    item = await lts.aget(("ns",), "k1")
    assert item is None or getattr(item, "value", None) is None


@pytest.mark.asyncio
async def test_build_memory_context_empty() -> None:
    ctx = await build_memory_context()
    assert ctx == ""


@pytest.mark.asyncio
async def test_build_memory_context_with_session() -> None:
    sm = SessionMemory(store=InMemoryStore())
    await sm.aadd_turn("t1", "prev_q", "prev_a")
    ctx = await build_memory_context(session=sm, thread_id="t1")
    assert "prev_q" in ctx


@pytest.mark.asyncio
async def test_build_memory_context_truncation() -> None:
    sm = SessionMemory(store=InMemoryStore())
    await sm.aadd_turn("t1", "x" * 5000, "y" * 5000)
    ctx = await build_memory_context(session=sm, thread_id="t1", max_chars=100)
    assert len(ctx) <= 100


def test_create_memory_tools_count() -> None:
    lts = LongTermStore(store=InMemoryStore())
    tools = create_memory_tools(lts)
    assert len(tools) == 2
    assert tools[0].name == "save_memory"
    assert tools[1].name == "recall_memory"


def test_save_memory_ephemeral_namespace_message() -> None:
    lts = LongTermStore(store=InMemoryStore())
    save_tool = create_memory_tools(lts)[0]
    out = save_tool.invoke({"key": "k", "content": "hello"}, config={"configurable": {}})
    assert "non-persistent" in out
    assert "OK: Saved" not in out


def test_save_memory_persistent_namespace_success_prefix() -> None:
    lts = LongTermStore(store=InMemoryStore())
    save_tool = create_memory_tools(lts)[0]
    cfg = {"configurable": {"memory_namespace": ("mem", "user-1")}}
    out = save_tool.invoke({"key": "k", "content": "hello"}, config=cfg)
    assert out.startswith("OK: Saved")


def test_recall_memory_ephemeral_warns_when_empty() -> None:
    lts = LongTermStore(store=InMemoryStore())
    recall_tool = create_memory_tools(lts)[1]
    out = recall_tool.invoke({"query": "anything"}, config={"configurable": {}})
    assert "non-persistent" in out
    assert "No relevant memories found" in out
