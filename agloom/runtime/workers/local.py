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
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Protocol

from ...protocol.emitter import AsyncSessionEmitter
from ..translator import translate
from . import BaseWorker
from .types import TaskStatus, WorkerHealth, WorkerTask, WorkerType

logger = logging.getLogger(__name__)

_DEFAULT_AI_CAPS = ["agent:local", "agent:react", "agent:cot"]


class _SupportsAStreamEvents(Protocol):
    def astream_events(self, prompt: str, *, thread_id: str) -> AsyncIterator[Any]: ...


class LocalAIWorker(BaseWorker):
    """Executes ``agent.invoke`` tasks by calling ``agent.astream_events()``.

    One instance is typically shared across turns within a session; each turn
    uses a separate LangGraph *thread* for isolation.
    """

    worker_type = WorkerType.LOCAL_AI

    def __init__(
        self,
        worker_id: str,
        agent: _SupportsAStreamEvents,
        extra_capabilities: list[str] | None = None,
        max_concurrency: int = 1,
    ) -> None:
        caps = list(_DEFAULT_AI_CAPS) + (extra_capabilities or [])
        super().__init__(worker_id=worker_id, capabilities=caps, max_concurrency=max_concurrency)
        self._agent: _SupportsAStreamEvents = agent

    # ── BaseWorker protocol ───────────────────────────────────────────────────

    async def execute(self, task: WorkerTask, emitter: AsyncSessionEmitter) -> None:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(UTC)
        task.attempt += 1
        cur = asyncio.current_task()
        if cur is not None:
            self._active_tasks[task.task_id] = cur
        self._mark_busy()

        prompt: str = task.payload.get("prompt", "")
        thread: str = task.thread
        output_bytes = 0

        # Announce this worker on the AGP wire
        emitter.emit_worker_spawned(
            worker_id=self.worker_id,
            name=self.__class__.__name__,
            pattern="local",
            task=prompt[:80] if prompt else None,
        )

        try:
            async for agent_event in self._agent.astream_events(
                prompt, thread_id=thread
            ):
                if agent_event.type in ("token", "done", "answer", "message_assistant"):
                    data = agent_event.data or {}
                    for key in ("output", "text", "content"):
                        chunk = data.get(key)
                        if isinstance(chunk, str):
                            output_bytes += len(chunk.encode("utf-8"))
                            break
                    if agent_event.type == "done" and isinstance(data.get("result"), dict):
                        out = data["result"].get("output")
                        if isinstance(out, str) and out:
                            output_bytes = max(output_bytes, len(out.encode("utf-8")))
                translate(agent_event, emitter)

            task.status = TaskStatus.COMPLETED
            task.finished_at = datetime.now(UTC)
            self._total_completed += 1

            emitter.emit_worker_completed(
                worker_id=self.worker_id,
                output_bytes=output_bytes,
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
