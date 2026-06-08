"""Session budget tracker concurrency."""

from __future__ import annotations

import asyncio

import pytest

from agloom.runtime.budget_tracker import SessionBudgetTracker


@pytest.mark.asyncio
async def test_reserve_invoke_slot_blocks_when_exhausted() -> None:
    tracker = SessionBudgetTracker(token_limit=10)
    tracker._cum_tokens = 10
    assert tracker.is_invoke_blocked() is True
    assert await tracker.reserve_invoke_slot() is False


@pytest.mark.asyncio
async def test_record_tokens_delta_is_thread_safe() -> None:
    tracker = SessionBudgetTracker(token_limit=10_000)

    class _Emitter:
        def emit_metric_budget_exhausted(self, **_: object) -> None:
            return None

        def emit_metric_budget_approaching(self, **_: object) -> None:
            return None

    emitter = _Emitter()

    async def _add() -> None:
        tracker.record_tokens_delta(emitter, input_tokens=5, output_tokens=5)  # type: ignore[arg-type]

    await asyncio.gather(*(_add() for _ in range(50)))
    assert tracker.cumulative_tokens == 500
