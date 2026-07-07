"""Assemble session + long-term memory into a context string for prompt injection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..context.plane import ContextBudget, compute_context_budget, ensure_memory_context_within_budget
from ..src.logging_utils import get_logger

if TYPE_CHECKING:
    from .session import SessionMemory
    from .store import LongTermStore

logger = get_logger(__name__)


async def build_memory_context(
    session: SessionMemory | None = None,
    store: LongTermStore | None = None,
    thread_id: str = "",
    namespace: tuple = (),
    query: str = "",
    last_n: int = 3,
    store_limit: int = 3,
    *,
    llm: Any = None,
    context_window_tokens: int | None = None,
    summarizer_model: Any | None = None,
) -> str:
    """Concatenate session recap and LT search hits; summarize when over budget (never chop)."""
    parts: list[str] = []

    if session is not None and thread_id:
        try:
            session_ctx = await session.aformat_context(thread_id, last_n=last_n)
            if session_ctx:
                parts.append(session_ctx)
        except Exception as exc:
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
    if llm is not None:
        budget = compute_context_budget(llm, context_window_tokens=context_window_tokens)
        summarizer = summarizer_model or getattr(session, "summarizer_model", None)
        context = await ensure_memory_context_within_budget(
            context,
            budget=budget,
            summarizer_model=summarizer,
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

    return "\n\n".join(parts)
