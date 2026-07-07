"""Context Plane AGP emission helpers."""

from __future__ import annotations

from typing import Any, Literal

from ..src.logging_utils import get_logger

logger = get_logger(__name__)


async def emit_context_summarized(
    *,
    scope: Literal["session", "harness", "job", "injection"] = "session",
    turns_before: int | None = None,
    turns_after: int | None = None,
    tokens_before: int | None = None,
    tokens_after: int | None = None,
    artifact_refs: list[str] | None = None,
    content_hash: str | None = None,
    event_queue: Any = None,
) -> None:
    data = {
        "scope": scope,
        "turns_before": turns_before,
        "turns_after": turns_after,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "artifact_refs": artifact_refs or [],
        "content_hash": content_hash,
    }
    try:
        from ..runtime.invocation_context import get_invocation_emitter

        emitter = get_invocation_emitter()
        if emitter is not None:
            emitter.emit_context_summarized(
                scope=scope,
                turns_before=turns_before,
                turns_after=turns_after,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                artifact_refs=artifact_refs,
                content_hash=content_hash,
            )
    except Exception as exc:
        logger.debug(f"context.summarized sync emit failed: {exc!r}")

    if event_queue is None:
        return
    try:
        from ..src.models import AgentEvent

        await event_queue.put(AgentEvent(type="context_summarized", data=data))
    except Exception as exc:
        logger.debug(f"context.summarized queue emit failed: {exc!r}")
