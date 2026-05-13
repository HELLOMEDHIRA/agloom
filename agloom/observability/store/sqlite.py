"""
agloom.observability.store.sqlite
──────────────────────────────────
SQLite-backed observability store.

Appends every AGP Envelope to an ``events`` table and materialises
per-session summary rows in ``sessions``.  All I/O is async (aiosqlite).

Schema is append-only and migration-safe: columns are never removed,
only added.  The store is designed to be opened once per runtime
process and shared across all sessions via a single connection pool.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import aiosqlite

# ── DDL ───────────────────────────────────────────────────────────────────────

_CREATE_EVENTS = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT    NOT NULL,
    thread_id   TEXT,
    run_id      TEXT,
    seq         INTEGER NOT NULL,
    event_type  TEXT    NOT NULL,
    ts          TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  INTEGER NOT NULL
);
"""

_CREATE_IDX_SESSION = "CREATE INDEX IF NOT EXISTS idx_ev_session ON events(session_id, seq);"
_CREATE_IDX_TYPE = "CREATE INDEX IF NOT EXISTS idx_ev_type    ON events(event_type);"
_CREATE_IDX_TS = "CREATE INDEX IF NOT EXISTS idx_ev_ts      ON events(created_at);"
_CREATE_UNIQ_SESSION_SEQ = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_ev_session_seq ON events(session_id, seq);"
)

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT    PRIMARY KEY,
    thread_id     TEXT,
    started_at    TEXT    NOT NULL,
    ended_at      TEXT,
    status        TEXT    NOT NULL DEFAULT 'open',
    pattern       TEXT,
    total_turns   INTEGER NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER
);
"""

_CREATE_IDX_SESSION_STATUS = "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);"

_SCHEMA = [
    _CREATE_EVENTS,
    _CREATE_IDX_SESSION,
    _CREATE_IDX_TYPE,
    _CREATE_IDX_TS,
    _CREATE_UNIQ_SESSION_SEQ,
    _CREATE_SESSIONS,
    _CREATE_IDX_SESSION_STATUS,
]

# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class SessionSummary:
    session_id:    str
    thread_id:     str | None
    started_at:    str
    ended_at:      str | None
    status:        str
    pattern:       str | None
    total_turns:   int
    input_tokens:  int
    output_tokens: int
    duration_ms:   int | None

@dataclass
class EventRow:
    id:          int
    session_id:  str
    thread_id:   str | None
    run_id:      str | None
    seq:         int
    event_type:  str
    ts:          str
    payload:     dict[str, Any]
    created_at:  int

# ── Store ─────────────────────────────────────────────────────────────────────

class SQLiteObservabilityStore:
    """
    Thread-safe async SQLite store for AGP Envelopes.

    Usage::

        store = await SQLiteObservabilityStore.open("sessions.db")
        await store.ingest(envelope_dict)
        sessions = await store.list_sessions()
        events = await store.get_events("s_abc123")
    """

    def __init__(self, db: aiosqlite.Connection, path: str) -> None:
        self._db = db
        self.path = path
        self._ingest_lock = asyncio.Lock()
        self._pending_commits = 0

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    async def open(cls, path: str = "agloom_obs.db") -> SQLiteObservabilityStore:
        db = await aiosqlite.connect(path, check_same_thread=False)
        db.row_factory = aiosqlite.Row
        # WAL mode for concurrent readers
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA synchronous=NORMAL;")
        for stmt in _SCHEMA:
            await db.execute(stmt)
        await db.commit()
        return cls(db, path)

    async def close(self) -> None:
        async with self._ingest_lock:
            await self._db.commit()
            self._pending_commits = 0
        await self._db.close()

    # ── Ingest ────────────────────────────────────────────────────────────────

    async def ingest(self, envelope: dict[str, Any]) -> None:
        """Persist a single AGP Envelope dict.  Idempotent on (session_id, seq)."""
        async with self._ingest_lock:
            session_id = envelope.get("session", "")
            thread_id = envelope.get("thread")
            run_id = envelope.get("run_id")
            seq = int(envelope.get("seq", 0))
            event_type = str(envelope.get("type", "unknown"))
            ts = str(envelope.get("ts", ""))
            now_ms = int(time.time() * 1000)

            await self._db.execute(
                """
                INSERT OR IGNORE INTO events
                    (session_id, thread_id, run_id, seq, event_type, ts, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, thread_id, run_id, seq, event_type, ts, json.dumps(envelope), now_ms),
            )

            # Upsert session summary
            data = envelope.get("data", {}) or {}
            if event_type == "session.opened":
                await self._db.execute(
                    """
                    INSERT OR IGNORE INTO sessions (session_id, thread_id, started_at, status)
                    VALUES (?, ?, ?, 'open')
                    """,
                    (session_id, thread_id, ts),
                )
            elif event_type == "session.closed":
                reason = data.get("reason", "unknown")
                dur = data.get("duration_ms")
                status = "error" if reason == "error" else "closed"
                await self._db.execute(
                    """
                    UPDATE sessions SET ended_at=?, status=?, duration_ms=?
                    WHERE session_id=?
                    """,
                    (ts, status, dur, session_id),
                )
            elif event_type == "pattern.classified":
                await self._db.execute(
                    "UPDATE sessions SET pattern=? WHERE session_id=?",
                    (data.get("pattern"), session_id),
                )
            elif event_type == "message.user":
                await self._db.execute(
                    "UPDATE sessions SET total_turns = total_turns + 1 WHERE session_id=?",
                    (session_id,),
                )
            elif event_type == "metric.tokens":
                await self._db.execute(
                    """
                    UPDATE sessions
                    SET input_tokens  = input_tokens  + ?,
                        output_tokens = output_tokens + ?
                    WHERE session_id=?
                    """,
                    (data.get("input_tokens", 0), data.get("output_tokens", 0), session_id),
                )

            self._pending_commits += 1
            if self._pending_commits >= 50:
                await self._db.commit()
                self._pending_commits = 0

    # ── Query: sessions ───────────────────────────────────────────────────────

    async def list_sessions(
        self,
        *,
        limit:  int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[SessionSummary]:
        q = "SELECT * FROM sessions"
        params: list[Any] = []
        if status:
            q += " WHERE status=?"
            params.append(status)
        q += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        async with self._db.execute(q, params) as cur:
            rows = await cur.fetchall()
        return [_row_to_summary(r) for r in rows]

    async def get_session(self, session_id: str) -> SessionSummary | None:
        async with self._db.execute(
            "SELECT * FROM sessions WHERE session_id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_summary(row) if row else None

    async def session_count(self) -> int:
        async with self._db.execute("SELECT COUNT(*) FROM sessions") as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ── Query: events ─────────────────────────────────────────────────────────

    async def get_events(
        self,
        session_id: str,
        *,
        event_types: list[str] | None = None,
        limit:  int = 500,
        offset: int = 0,
        after_seq: int | None = None,
    ) -> list[EventRow]:
        q = "SELECT * FROM events WHERE session_id=?"
        params: list[Any] = [session_id]
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            q += f" AND event_type IN ({placeholders})"
            params.extend(event_types)
        if after_seq is not None:
            q += " AND seq > ?"
            params.append(after_seq)
        q += " ORDER BY seq ASC LIMIT ? OFFSET ?"
        params += [limit, offset]
        async with self._db.execute(q, params) as cur:
            rows = await cur.fetchall()
        return [_row_to_event(r) for r in rows]

    async def get_event_count(self, session_id: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM events WHERE session_id=?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def get_latest_events(
        self,
        *,
        limit: int = 100,
        event_types: list[str] | None = None,
    ) -> list[EventRow]:
        """Most recent N events across all sessions — for the live feed."""
        q = "SELECT * FROM events"
        params: list[Any] = []
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            q += f" WHERE event_type IN ({placeholders})"
            params.extend(event_types)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        async with self._db.execute(q, params) as cur:
            rows = await cur.fetchall()
        return list(reversed([_row_to_event(r) for r in rows]))

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_session(self, session_id: str) -> None:
        async with self._ingest_lock:
            await self._db.execute("DELETE FROM events  WHERE session_id=?", (session_id,))
            await self._db.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            await self._db.commit()
            self._pending_commits = 0


# ── Row converters ────────────────────────────────────────────────────────────

def _row_to_summary(r: aiosqlite.Row) -> SessionSummary:
    return SessionSummary(
        session_id=r["session_id"],
        thread_id=r["thread_id"],
        started_at=r["started_at"],
        ended_at=r["ended_at"],
        status=r["status"],
        pattern=r["pattern"],
        total_turns=r["total_turns"],
        input_tokens=r["input_tokens"],
        output_tokens=r["output_tokens"],
        duration_ms=r["duration_ms"],
    )

def _row_to_event(r: aiosqlite.Row) -> EventRow:
    return EventRow(
        id=r["id"],
        session_id=r["session_id"],
        thread_id=r["thread_id"],
        run_id=r["run_id"],
        seq=r["seq"],
        event_type=r["event_type"],
        ts=r["ts"],
        payload=json.loads(r["payload"]),
        created_at=r["created_at"],
    )
