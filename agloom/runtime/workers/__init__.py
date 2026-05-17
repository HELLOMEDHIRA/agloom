"""BaseWorker — the actor protocol every worker must implement.

A *Worker* is the fundamental execution unit of agloom-runtime.  Each worker:

- Has a stable identity (``worker_id``) and a set of capability tags.
- Processes one :class:`WorkerTask` at a time (or up to ``max_concurrency``
  tasks concurrently for workers that support it).
- Streams progress by emitting AGP events through the supplied
  :class:`~agloom.protocol.AsyncSessionEmitter`.
- Reports health on demand via :meth:`health_check`.

Workers are managed by :class:`~agloom.runtime.pool.WorkerPool` and are never
instantiated directly by application code.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from ...protocol import AsyncSessionEmitter
from .types import RetryPolicy, WorkerHealth, WorkerStatus, WorkerTask, WorkerType

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """Abstract base class for all agloom-runtime workers.

    Subclasses must implement :meth:`execute` and :meth:`health_check`.
    ``start`` / ``stop`` are optional lifecycle hooks (default: no-op).
    """

    worker_type: WorkerType = WorkerType.CUSTOM

    def __init__(
        self,
        worker_id: str,
        capabilities: list[str],
        max_concurrency: int = 1,
        retry_policy: RetryPolicy | None = None,
        health_interval_s: float = 30.0,
    ) -> None:
        self.worker_id = worker_id
        self.capabilities: list[str] = capabilities
        self.max_concurrency = max_concurrency
        self.retry_policy = retry_policy or RetryPolicy()
        self.health_interval_s = health_interval_s

        self._status: WorkerStatus = WorkerStatus.STARTING
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._total_completed = 0
        self._total_failed = 0
        self._started_at: datetime | None = None
        self._last_error: str | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Acquire worker resources (connections, model loading, etc.).

        Called once by :class:`~agloom.runtime.pool.WorkerPool` before the
        worker receives any tasks.  Default implementation is a no-op.
        """
        self._status = WorkerStatus.IDLE
        self._started_at = datetime.now(UTC)
        logger.debug("Worker %s started (%s)", self.worker_id, self.worker_type.value)

    async def stop(self) -> None:
        """Drain in-flight tasks and release resources.

        Called by :class:`~agloom.runtime.pool.WorkerPool` during shutdown.
        Cancels all running tasks after a grace period.
        """
        self._status = WorkerStatus.DRAINING
        if self._active_tasks:
            logger.info(
                "Worker %s draining %d active task(s)…", self.worker_id, len(self._active_tasks)
            )
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
        self._status = WorkerStatus.STOPPED
        logger.debug("Worker %s stopped", self.worker_id)

    # ── Core protocol ─────────────────────────────────────────────────────────

    @abstractmethod
    async def execute(self, task: WorkerTask, emitter: AsyncSessionEmitter) -> None:
        """Execute *task* and stream AGP events through *emitter*.

        This method MUST:
        - Set ``task.status = TaskStatus.RUNNING`` at the start.
        - Set ``task.status = TaskStatus.COMPLETED`` (or FAILED) before returning.
        - Stream all meaningful work through *emitter* as typed AGP events.
        - NOT raise exceptions for task-level failures (catch and mark FAILED).
        - RAISE ``asyncio.CancelledError`` if cancelled (do not swallow it).
        """

    @abstractmethod
    async def health_check(self) -> WorkerHealth:
        """Return a snapshot of the worker's current health."""

    # ── Capacity helpers ──────────────────────────────────────────────────────

    @property
    def status(self) -> WorkerStatus:
        return self._status

    @property
    def is_available(self) -> bool:
        """True when the worker can accept a new task."""
        return (
            self._status == WorkerStatus.IDLE
            and len(self._active_tasks) < self.max_concurrency
        )

    def has_capabilities(self, required: list[str]) -> bool:
        """Return True if *all* required capability tags are present."""
        if not required:
            return True
        caps = set(self.capabilities)
        return all(
            r in caps or any(c.startswith(r.split(":")[0] + ":") for c in caps)
            for r in required
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _mark_busy(self) -> None:
        if len(self._active_tasks) >= self.max_concurrency:
            self._status = WorkerStatus.BUSY

    def _mark_idle_if_free(self) -> None:
        if len(self._active_tasks) < self.max_concurrency:
            self._status = WorkerStatus.IDLE

    def _uptime_s(self) -> float:
        if self._started_at:
            return (datetime.now(UTC) - self._started_at).total_seconds()
        return 0.0

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} id={self.worker_id!r} "
            f"caps={self.capabilities} status={self._status.value}>"
        )


__all__ = ["BaseWorker"]
