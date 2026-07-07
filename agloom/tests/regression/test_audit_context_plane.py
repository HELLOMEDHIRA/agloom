"""Context Plane: summarize path, no tail chop."""

import pytest

from agloom.context.plane import ContextBudget, assemble_memory_context, compute_context_budget
from agloom.context.summarize import summarize_oldest_turns_sync
from agloom.memory.injection import build_memory_context


class _FakeLLM:
    pass


class _FakeSumm:
    def invoke(self, messages):
        class R:
            content = "compressed summary"

        return R()


def test_assemble_memory_context_never_chops():
    budget = ContextBudget(context_window=8192, reserved_output=1024, input_budget=100, digest_min_chars=500)
    text = "x" * 10_000
    out, over = assemble_memory_context(text, budget=budget)
    assert out == text
    assert over is True


def test_episodic_summarize_replaces_oldest_turns():
    turns = [{"q": f"q{i}", "a": f"a{i}"} for i in range(6)]
    compressed, episodic = summarize_oldest_turns_sync(turns, summarizer_model=_FakeSumm())
    assert len(compressed) < len(turns)
    assert episodic is not None
    assert compressed[0]["q"] == "[SUMMARY]"


@pytest.mark.asyncio
async def test_build_memory_context_preserves_full_turns_without_llm():
    from agloom.memory.session import SessionMemory
    from langgraph.store.memory import InMemoryStore

    sm = SessionMemory(store=InMemoryStore(), summarizer_model=None)
    await sm.aadd_turn("t1", "alpha" * 200, "beta" * 200)
    ctx = await build_memory_context(session=sm, thread_id="t1")
    assert "alpha" in ctx


def test_digest_min_chars_from_window():
    budget = compute_context_budget(_FakeLLM(), context_window_tokens=128_000)
    assert 500 <= budget.digest_min_chars <= 4000
