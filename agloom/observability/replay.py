"""
agloom.observability.replay
────────────────────────────
ReplayEngine — re-emits stored AGP events as an async generator.

The caller controls the speed multiplier:
  speed=1.0  → real-time (original wall-clock intervals)
  speed=2.0  → 2× faster
  speed=0    → instant (no sleep)

Replay and live execution produce identical AGP envelope streams.
The frontend cannot distinguish replay from live — ensuring full UX parity.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from .store import SQLiteObservabilityStore


class ReplayEngine:
    """
    Usage::

        engine = ReplayEngine(store)
        async for envelope in engine.replay("s_abc123", speed=1.0):
            await ws.send_json(envelope)
    """

    def __init__(self, store: SQLiteObservabilityStore) -> None:
        self._store = store

    async def replay(
        self,
        session_id: str,
        *,
        speed: float = 1.0,
        after_seq: int | None = None,
        event_types: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        """
        Async-generator that yields AGP Envelope dicts in sequence order.
        Sleeps between events to preserve the original timing (modulated by *speed*).
        """
        events = await self._store.get_events(
            session_id,
            limit=10_000,
            after_seq=after_seq,
            event_types=event_types,
        )

        if not events:
            return

        prev_ts: datetime | None = None

        for ev in events:
            try:
                cur_ts = datetime.fromisoformat(ev.ts.replace("Z", "+00:00"))
            except ValueError:
                cur_ts = datetime.now(tz=UTC)

            if speed > 0 and prev_ts is not None:
                delta = (cur_ts - prev_ts).total_seconds()
                if delta > 0:
                    await asyncio.sleep(delta / speed)

            prev_ts = cur_ts
            yield ev.payload

    async def replay_ndjson(
        self,
        session_id: str,
        *,
        speed: float = 1.0,
    ) -> AsyncIterator[str]:
        """Convenience wrapper yielding newline-delimited JSON strings."""
        async for envelope in self.replay(session_id, speed=speed):
            yield json.dumps(envelope) + "\n"
