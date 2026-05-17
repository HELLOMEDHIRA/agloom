"""Regression tests for external code-review findings."""

from __future__ import annotations

import pytest

from agloom.patterns._blackboard_state import _value_marks_explicit_ks_failure
from agloom.protocol.store import SqliteEventStore


def test_blackboard_does_not_treat_benign_error_prefix_as_failure() -> None:
    assert _value_marks_explicit_ks_failure("error: completed successfully") is False
    assert _value_marks_explicit_ks_failure("error: timeout contacting API") is True


@pytest.mark.asyncio
async def test_sqlite_replay_skips_corrupt_rows_without_infinite_loop() -> None:
    store = SqliteEventStore(":memory:")
    conn = store._connect_unlocked()
    await store.append("s_bad", {"seq": 1, "type": "good"})
    conn.execute(
        "INSERT INTO agp_events (session, seq, type, payload) VALUES (?, ?, ?, ?)",
        ("s_bad", 2, "bad", "{not-json"),
    )
    conn.commit()
    await store.append("s_bad", {"seq": 3, "type": "good"})

    replayed = [e async for e in store.replay("s_bad")]
    assert len(replayed) == 2
    store.close()
