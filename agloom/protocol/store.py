"""AGP EventStore — append-only, replayable event log per session.

The EventStore is the persistence backbone for AGP replay and reconnect:

- ``SessionEmitter`` calls ``store.append(session_id, envelope_dict)`` via its
  ``on_emit`` callback after each event write.
- On ``command.session.resume`` the serve loop calls ``store.replay(session_id,
  from_seq=…)`` and forwards buffered events to the reconnecting client.

Two concrete implementations are provided:

``MemoryEventStore``
    In-process, ephemeral.  Suitable for tests and single-process deploys where
    persistence is not needed.

``SqliteEventStore``
    Durable, append-only SQLite backend using the stdlib ``sqlite3`` module (no
    extra dep).  Events are stored as NDJSON rows in a ``events`` table.  WAL
    mode is enabled by default so reads (replay) do not block concurrent writes.

Both implementations are safe for concurrent async tasks (one writer + many
readers) within a single process.  Cross-process concurrency requires an
external broker (Phase 2).

Usage::

    store = MemoryEventStore()
    # wire into SessionEmitter via on_emit
    emitter = SessionEmitter(session="s_1", thread="t_1",
                             on_emit=lambda e: asyncio.ensure_future(
                                 store.append("s_1", emitter.event_to_dict(e))
                             ))

    # replay on reconnect
    async for raw in store.replay("s_1", from_seq=0):
        await websocket.send(raw)
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path


class EventStore(ABC):
    """Abstract append-only event log for AGP sessions."""

    @abstractmethod
    async def append(self, session_id: str, event: dict) -> None:
        """Append a serialised :class:`~agloom.protocol.Envelope` to the log.

        ``event`` is a plain dict as returned by :func:`~agloom.protocol.emitter.event_to_dict`.
        The dict MUST carry a ``seq`` field (monotonic int) for replay ordering.
        """

    @abstractmethod
    def replay(self, session_id: str, *, from_seq: int = 0) -> AsyncIterator[dict]:
        """Async generator yielding all stored events with ``seq >= from_seq``
        in ascending ``seq`` order.

        This is a sync-returning generator factory (no ``await`` needed at call
        site) — ``async for raw in store.replay(…)`` works directly.
        """

    @abstractmethod
    async def count(self, session_id: str) -> int:
        """Return the number of events stored for ``session_id``."""

    @abstractmethod
    async def clear(self, session_id: str) -> None:
        """Delete all events for ``session_id``.  Useful for tests and TTL eviction."""

    @abstractmethod
    async def list_session_ids(self) -> list[str]:
        """Return distinct session ids that have at least one stored event, sorted lexically."""

    @abstractmethod
    async def rename_session(self, old_session_id: str, new_session_id: str) -> None:
        """Move all stored events from *old_session_id* to *new_session_id* (replay key migration)."""


# ── MemoryEventStore ───────────────────────────────────────────────────────────


class MemoryEventStore(EventStore):
    """Thread-safe, in-process event store backed by a plain Python dict.

    Events are kept in insertion order.  The ``asyncio.Lock`` guards concurrent
    ``append`` calls when multiple tasks share the same store instance.
    """

    def __init__(self) -> None:
        self._store: dict[str, list[dict]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def append(self, session_id: str, event: dict) -> None:
        async with self._lock:
            self._store.setdefault(session_id, []).append(event)

    async def replay(self, session_id: str, *, from_seq: int = 0) -> AsyncIterator[dict]:  # type: ignore[override]
        events = list(self._store.get(session_id, []))
        for evt in events:
            if evt.get("seq", 0) >= from_seq:
                yield evt
                await asyncio.sleep(0)  # cooperate with the event loop

    async def count(self, session_id: str) -> int:
        return len(self._store.get(session_id, []))

    async def clear(self, session_id: str) -> None:
        async with self._lock:
            self._store.pop(session_id, None)

    async def list_session_ids(self) -> list[str]:
        async with self._lock:
            return sorted(self._store.keys())

    async def rename_session(self, old_session_id: str, new_session_id: str) -> None:
        async with self._lock:
            moved = self._store.pop(old_session_id, None)
            if not moved:
                return
            bucket = self._store.setdefault(new_session_id, [])
            bucket.extend(moved)
            bucket.sort(key=lambda e: e.get("seq", 0))


# ── SqliteEventStore ───────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agp_events (
    rowid    INTEGER PRIMARY KEY AUTOINCREMENT,
    session  TEXT    NOT NULL,
    seq      INTEGER NOT NULL,
    type     TEXT    NOT NULL,
    payload  TEXT    NOT NULL,
    ts       TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS agp_events_session_seq ON agp_events (session, seq);
"""


class SqliteEventStore(EventStore):
    """Durable event store backed by SQLite (stdlib, no extra dependency).

    ``db_path`` defaults to ``:memory:`` for test convenience but any file path
    works.  WAL mode is enabled at construction so readers (``replay``) do not
    block writers (``append``).

    The connection is created lazily on the first call to ``append`` or ``replay``
    and is reused across all calls.  Asyncio tasks run the blocking SQLite calls
    in a thread-pool executor so the event loop is never blocked.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn: sqlite3.Connection | None = None
        self._write_lock: asyncio.Lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    def _sync_append(self, session_id: str, event: dict) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO agp_events (session, seq, type, payload) VALUES (?, ?, ?, ?)",
            (session_id, event.get("seq", 0), event.get("type", ""), json.dumps(event, ensure_ascii=False)),
        )
        conn.commit()

    def _sync_replay(self, session_id: str, from_seq: int) -> list[dict]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT payload FROM agp_events WHERE session = ? AND seq >= ? ORDER BY seq",
            (session_id, from_seq),
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def _sync_count(self, session_id: str) -> int:
        conn = self._connect()
        row = conn.execute("SELECT COUNT(*) FROM agp_events WHERE session = ?", (session_id,)).fetchone()
        return row[0] if row else 0

    def _sync_clear(self, session_id: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM agp_events WHERE session = ?", (session_id,))
        conn.commit()

    def _sync_list_sessions(self) -> list[str]:
        conn = self._connect()
        rows = conn.execute("SELECT DISTINCT session FROM agp_events ORDER BY session").fetchall()
        return [str(r[0]) for r in rows]

    def _sync_rename_session(self, old_session_id: str, new_session_id: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE agp_events SET session = ? WHERE session = ?",
            (new_session_id, old_session_id),
        )
        conn.commit()

    async def rename_session(self, old_session_id: str, new_session_id: str) -> None:
        loop = asyncio.get_running_loop()
        async with self._write_lock:
            await loop.run_in_executor(None, self._sync_rename_session, old_session_id, new_session_id)

    async def append(self, session_id: str, event: dict) -> None:
        loop = asyncio.get_running_loop()
        async with self._write_lock:
            await loop.run_in_executor(None, self._sync_append, session_id, event)

    async def replay(self, session_id: str, *, from_seq: int = 0) -> AsyncIterator[dict]:  # type: ignore[override]
        loop = asyncio.get_running_loop()
        events: list[dict] = await loop.run_in_executor(None, self._sync_replay, session_id, from_seq)
        for evt in events:
            yield evt
            await asyncio.sleep(0)

    async def count(self, session_id: str) -> int:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_count, session_id)

    async def clear(self, session_id: str) -> None:
        loop = asyncio.get_running_loop()
        async with self._write_lock:
            await loop.run_in_executor(None, self._sync_clear, session_id)

    async def list_session_ids(self) -> list[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_list_sessions)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __del__(self) -> None:
        self.close()


__all__ = [
    "EventStore",
    "MemoryEventStore",
    "SqliteEventStore",
]
