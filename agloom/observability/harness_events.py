"""Emit harness.* AGP events from production harness paths."""

from __future__ import annotations

from typing import Any

from ..src.logging_utils import get_logger
from ..src.models import AgentEvent

logger = get_logger(__name__)


async def emit_harness_task_updated(
    *,
    task_id: str,
    status: str,
    notes: str = "",
    project: str | None = None,
    event_queue: Any = None,
) -> None:
    """Notify AGP consumers that a harness ledger task changed."""
    data = {
        "task_id": task_id,
        "status": status,
        "notes": notes,
        "project": project,
    }
    try:
        from ..runtime.invocation_context import get_invocation_emitter

        emitter = get_invocation_emitter()
        if emitter is not None:
            emitter.emit_harness_task_updated(
                task_id=task_id,
                status=status,
                notes=notes,
                project=project,
            )
            return
    except Exception as exc:
        logger.debug(f"harness.task.updated emitter path failed: {exc!r}")

    if event_queue is not None:
        try:
            await event_queue.put(AgentEvent(type="harness_task_updated", data=data))
        except Exception as exc:
            logger.debug(f"harness.task.updated queue path failed: {exc!r}")
