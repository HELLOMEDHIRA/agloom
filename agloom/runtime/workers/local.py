"""LocalAIWorker — in-process worker that wraps a UnifiedAgent.

This is the standard single-node worker. It receives an
``agent.invoke`` :class:`WorkerTask`, calls the agent's ``astream_events()``
generator, and pipes every :class:`AgentEvent` through the
:class:`~agloom.runtime.translator.Translator` onto the AGP wire.

For scaling and topology notes see ``docs/runtime/architecture.md``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from ...protocol.emitter import AsyncSessionEmitter
from ..translator import translate
from . import BaseWorker
from .types import TaskStatus, WorkerHealth, WorkerTask, WorkerType

logger = logging.getLogger(__name__)

_DEFAULT_AI_CAPS = ["agent:local", "agent:react", "agent:cot"]


class LocalAIWorker(BaseWorker):
    """Executes ``agent.invoke`` tasks by calling ``agent.astream_events()``.

    One instance is typically shared across turns within a session; each turn
    uses a separate LangGraph *thread* for isolation.
    """

    worker_type = WorkerType.LOCAL_AI

    def __init__(
        self,
        worker_id: str,
        agent: object,  # UnifiedAgent — avoid hard import at module level
        extra_capabilities: list[str] | None = None,
        max_concurrency: int = 1,
    ) -> None:
        caps = list(_DEFAULT_AI_CAPS) + (extra_capabilities or [])
        super().__init__(worker_id=worker_id, capabilities=caps, max_concurrency=max_concurrency)
        self._agent = agent

    # ── BaseWorker protocol ───────────────────────────────────────────────────

    async def execute(self, task: WorkerTask, emitter: AsyncSessionEmitter) -> None:  # type: ignore[override]
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        task.attempt += 1
        self._mark_busy()

        prompt: str = task.payload.get("prompt", "")
        thread: str = task.thread

        # Announce this worker on the AGP wire
        emitter.emit_worker_spawned(
            worker_id=self.worker_id,
            name=self.__class__.__name__,
            pattern="local",
            task=prompt[:80] if prompt else None,
        )

        try:
            async for agent_event in self._agent.astream_events(  # type: ignore[union-attr]
                prompt, thread_id=thread
            ):
                envelope = translate(agent_event, emitter)
                if envelope is not None:
                    # translate() already called emitter._write(); this is a no-op path
                    pass

            task.status = TaskStatus.COMPLETED
            task.finished_at = datetime.now(UTC)
            self._total_completed += 1

            emitter.emit_worker_completed(
                worker_id=self.worker_id,
                output_bytes=0,
                duration_ms=task.duration_ms() or 0,
            )

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            task.finished_at = datetime.now(UTC)
            self._last_error = "cancelled"
            raise

        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.finished_at = datetime.now(UTC)
            self._total_failed += 1
            self._last_error = str(exc)

            emitter.emit_worker_failed(
                worker_id=self.worker_id,
                error=str(exc),
                duration_ms=task.duration_ms() or 0,
            )

            logger.exception("LocalAIWorker %s failed on task %s", self.worker_id, task.task_id)

        finally:
            self._active_tasks.pop(task.task_id, None)
            self._mark_idle_if_free()

    async def health_check(self) -> WorkerHealth:
        return WorkerHealth(
            worker_id=self.worker_id,
            status=self._status,
            active_tasks=len(self._active_tasks),
            total_tasks_completed=self._total_completed,
            total_tasks_failed=self._total_failed,
            uptime_s=self._uptime_s(),
            last_error=self._last_error,
        )


__all__ = ["LocalAIWorker"]
