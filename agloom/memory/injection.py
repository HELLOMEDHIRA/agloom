"""Assemble session + long-term memory into a context string for prompt injection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..logging_utils import get_logger

if TYPE_CHECKING:
    from .session import SessionMemory
    from .store import LongTermStore

logger = get_logger(__name__)

DEFAULT_MAX_CHARS = 4000  # Adjust per model: GPT-4o → 8000, Llama-70B → 4000


async def build_memory_context(
    session: SessionMemory | None = None,
    store: LongTermStore | None = None,
    thread_id: str = "",
    namespace: tuple = (),
    query: str = "",
    last_n: int = 3,
    store_limit: int = 3,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Concatenate session recap and LT search hits; trim to ``max_chars`` (tail preserved)."""
    parts: list[str] = []

    if session is not None and thread_id:
        try:
            session_ctx = await session.aformat_context(thread_id, last_n=last_n)
            if session_ctx:
                parts.append(session_ctx)
        except Exception as exc:
            # Never crash run_fresh for a memory read failure
            logger.warning(f"MemoryInjection: session read failed ({exc!r}) — skipping.")

    if store is not None and namespace and query:
        try:
            store_ctx = await store.aformat_context(namespace, query, limit=store_limit)
            if store_ctx:
                parts.append(store_ctx)
        except Exception as exc:
            logger.warning(f"MemoryInjection: store read failed ({exc!r}) — skipping.")

    if not parts:
        return ""

    context = "\n\n".join(parts)

    if len(context) > max_chars:
        original_len = len(context)
        context = context[-max_chars:]  # keep the most recent content
        logger.warning(
            f"MemoryInjection: context trimmed to {max_chars} chars "
            f"(was {original_len}, dropped {original_len - max_chars} chars). "
            f"Increase max_chars or reduce last_n/store_limit."
        )

    logger.debug(f"MemoryInjection: thread={thread_id!r} context={len(context)} chars injected")
    return context


def build_memory_context_sync(
    session: SessionMemory | None = None,
    store: LongTermStore | None = None,
    thread_id: str = "",
    namespace: tuple = (),
    query: str = "",
    last_n: int = 3,
    store_limit: int = 3,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Sync version — InMemoryStore only. For tests and CLI tools that cannot await."""
    parts: list[str] = []

    if session is not None and thread_id:
        try:
            ctx = session.format_context(thread_id, last_n=last_n)
            if ctx:
                parts.append(ctx)
        except Exception as exc:
            logger.warning(f"MemoryInjection(sync): session read failed ({exc!r}).")

    if store is not None and namespace and query:
        try:
            ctx = store.format_context(namespace, query, limit=store_limit)
            if ctx:
                parts.append(ctx)
        except Exception as exc:
            logger.warning(f"MemoryInjection(sync): store read failed ({exc!r}).")

    if not parts:
        return ""

    context = "\n\n".join(parts)
    if len(context) > max_chars:
        context = context[-max_chars:]
    return context
