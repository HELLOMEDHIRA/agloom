"""Per-AGP-session isolated :class:`~agloom.memory.session.SessionMemory` for runtime transports."""

from __future__ import annotations

import asyncio
import re
from argparse import Namespace
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from agloom.memory.session import SessionMemory

Cleanup = Callable[[], Awaitable[None]]


def _session_max_turns(args: Namespace) -> int:
    return int(getattr(args, "session_max_turns", 50) or 50)


def _summarize_budget_from_args(args: Namespace) -> int | None:
    raw = getattr(args, "max_tokens", None)
    if raw is None:
        return None
    try:
        n = int(raw)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _safe_session_slug(session_id: str) -> str:
    return re.sub(r"[^\w.\-+=]", "_", session_id.strip()) or "session"


def _prepare_sqlite_path(raw: str, agp_session_id: str) -> Path:
    base = Path(raw).expanduser()
    p = (Path.cwd() / base).resolve() if not base.is_absolute() else base.resolve()
    safe = _safe_session_slug(agp_session_id)
    p = p.parent / f"{p.stem}_{safe}{p.suffix}"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _memory_type(args: Namespace) -> str:
    return (getattr(args, "memory_type", None) or "").strip().lower()


async def open_isolated_session_memory(
    args: Namespace,
    *,
    agp_session_id: str,
) -> tuple[SessionMemory | None, Cleanup | None]:
    """Return session memory scoped to one AGP ``session_id`` (stdio client or WS connection).

    * **sqlite** — separate DB file per ``agp_session_id`` (existing WS behaviour).
    * **in-memory** / **default** / **none** — dedicated :class:`~langgraph.store.memory.InMemoryStore`
      per ``agp_session_id`` so concurrent WebSocket sessions never share turn data.
    """
    mt = _memory_type(args)
    session_key = _safe_session_slug(agp_session_id)
    budget = _summarize_budget_from_args(args)
    auto_sum = bool(getattr(args, "auto_summarize", True))

    if mt == "sqlite":
        raw = getattr(args, "memory_path", None) or ".agloom/session_memory.sqlite"
        db_path = await asyncio.to_thread(_prepare_sqlite_path, str(raw), session_key)
        from contextlib import AsyncExitStack

        from langgraph.store.sqlite import AsyncSqliteStore

        stack = AsyncExitStack()
        store = await stack.enter_async_context(AsyncSqliteStore.from_conn_string(str(db_path)))
        await store.setup()
        sm = SessionMemory(
            store=store,
            max_turns=_session_max_turns(args),
            auto_summarize=auto_sum,
            summarize_max_tokens_budget=budget,
            agp_session_key=session_key,
        )

        async def cleanup() -> None:
            await stack.aclose()

        return sm, cleanup

    if mt == "none":
        from langgraph.store.memory import InMemoryStore

        return (
            SessionMemory(
                store=InMemoryStore(),
                max_turns=1,
                auto_summarize=False,
                agp_session_key=session_key,
            ),
            None,
        )

    if not mt or mt in ("default", "auto", "in-memory"):
        from langgraph.store.memory import InMemoryStore

        return (
            SessionMemory(
                store=InMemoryStore(),
                max_turns=_session_max_turns(args),
                auto_summarize=auto_sum,
                summarize_max_tokens_budget=budget,
                agp_session_key=session_key,
            ),
            None,
        )

    raise ValueError(f"unsupported --memory {mt!r} (try in-memory, none, sqlite)")


async def open_sqlite_session_memory(
    args: Namespace,
    *,
    ws_session_id: str | None = None,
) -> tuple[SessionMemory | None, Cleanup | None]:
    """Backward-compatible alias — prefer :func:`open_isolated_session_memory`."""
    if ws_session_id is None:
        mt = _memory_type(args)
        if mt != "sqlite":
            return None, None
        ws_session_id = "stdio"
    return await open_isolated_session_memory(args, agp_session_id=ws_session_id)


__all__ = ["Cleanup", "open_isolated_session_memory", "open_sqlite_session_memory"]
