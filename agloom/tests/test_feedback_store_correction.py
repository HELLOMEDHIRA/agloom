"""FeedbackStore correction memory (user_id namespace)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agloom.feedback.store import FeedbackStore


@pytest.mark.asyncio
async def test_apply_user_feedback_saves_correction_under_user_namespace() -> None:
    store_backend = MagicMock()
    store_backend.aget = AsyncMock(
        return_value=MagicMock(
            value={
                "run_id": "run_1",
                "query": "what is X?",
                "user_id": "user-42",
            },
        ),
    )
    store_backend.asave = AsyncMock()

    fb = FeedbackStore(store_backend, agent_name="agent-a")
    ok = await fb.apply_user_feedback(
        run_id="run_1",
        rating="positive",
        comment="",
        correct="X is 42",
    )
    assert ok is True

    correction_save = [
        c
        for c in store_backend.asave.await_args_list
        if c.kwargs.get("namespace") == ("memory", "agent-a", "user-42")
    ]
    assert len(correction_save) == 1
    assert correction_save[0].kwargs["key"] == "correction_run_1"
    assert "42" in correction_save[0].kwargs["value"]


@pytest.mark.asyncio
async def test_apply_user_feedback_correction_defaults_to_shared_without_user_id() -> None:
    store_backend = MagicMock()
    store_backend.aget = AsyncMock(
        return_value=MagicMock(value={"run_id": "run_2", "query": "q"}),
    )
    store_backend.asave = AsyncMock()

    fb = FeedbackStore(store_backend, agent_name="agent-b")
    await fb.apply_user_feedback(run_id="run_2", rating="ok", correct="fixed answer")

    namespaces = [c.kwargs.get("namespace") for c in store_backend.asave.await_args_list]
    assert ("memory", "agent-b", "shared") in namespaces
