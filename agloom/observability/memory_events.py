"""Emit memory.* AGP events from production write paths."""

from __future__ import annotations

from typing import Any

from ..src.logging_utils import get_logger
from ..src.models import AgentEvent

logger = get_logger(__name__)


def _preview(text: str, limit: int = 120) -> str:
    t = (text or "").strip()
    return t if len(t) <= limit else t[: limit - 3] + "..."


async def emit_memory_session_write(
    *,
    thread_id: str,
    query: str,
    output: str,
    turn_count: int | None = None,
    run_id: str | None = None,
    event_queue: Any = None,
) -> None:
    """Notify AGP consumers that a session turn was persisted."""
    data = {
        "thread": thread_id,
        "run_id": run_id,
        "query_preview": _preview(query),
        "output_preview": _preview(output),
        "turn_count": turn_count,
    }
    try:
        from ..runtime.invocation_context import get_invocation_emitter

        emitter = get_invocation_emitter()
        if emitter is not None:
            emitter.emit_memory_session_write(
                thread=thread_id,
                run_id=run_id,
                query_preview=data["query_preview"],
                output_preview=data["output_preview"],
                turn_count=turn_count,
            )
            return
    except Exception as exc:
        logger.debug(f"memory.session.write emitter path failed: {exc!r}")

    if event_queue is not None:
        try:
            await event_queue.put(AgentEvent(type="memory_session_write", data=data))
        except Exception as exc:
            logger.debug(f"memory.session.write queue path failed: {exc!r}")


def emit_memory_lt_store_sync(
    *,
    namespace: tuple | str,
    key: str,
    content: str,
) -> None:
    ns = "/".join(namespace) if isinstance(namespace, tuple) else namespace
    preview = _preview(content)
    try:
        from ..runtime.invocation_context import get_invocation_emitter

        emitter = get_invocation_emitter()
        if emitter is not None:
            emitter.emit_memory_lt_store(namespace=ns, key=key, content_preview=preview)
    except Exception as exc:
        logger.debug(f"memory.lt.store sync emit failed: {exc!r}")


async def emit_memory_lt_store(
    *,
    namespace: tuple | str,
    key: str,
    content: str,
    event_queue: Any = None,
) -> None:
    ns = "/".join(namespace) if isinstance(namespace, tuple) else namespace
    preview = _preview(content)
    data = {"namespace": ns, "key": key, "content_preview": preview}
    try:
        from ..runtime.invocation_context import get_invocation_emitter

        emitter = get_invocation_emitter()
        if emitter is not None:
            emitter.emit_memory_lt_store(namespace=ns, key=key, content_preview=preview)
            return
    except Exception as exc:
        logger.debug(f"memory.lt.store emitter path failed: {exc!r}")

    if event_queue is not None:
        try:
            await event_queue.put(AgentEvent(type="memory_lt_store", data=data))
        except Exception as exc:
            logger.debug(f"memory.lt.store queue path failed: {exc!r}")
