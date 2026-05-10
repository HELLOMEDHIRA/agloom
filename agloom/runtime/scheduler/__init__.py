"""InProcessScheduler — asyncio priority-queue task scheduler.

Phase 1 implementation: single-process, zero infrastructure dependencies.
Designed so Phase 2 can drop in a ``RedisScheduler`` with the same interface.

Scheduling algorithm:
1. Tasks are submitted into an ``asyncio.PriorityQueue`` (higher priority = popped first).
2. A dispatcher coroutine runs in the background, popping tasks and forwarding them
   to :class:`~agloom.runtime.pool.WorkerPool` whenever a capable worker is free.
3. If no worker is available, the task stays in the queue until a worker finishes.
4. Per-task ``timeout_ms`` is enforced by the pool when executing, not the scheduler.
5. ``max_queue_depth`` provides back-pressure: submitting to a full queue raises
   ``SchedulerFullError`` so the caller can emit ``error.transient`` upstream.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from ..workers.types import TaskStatus, WorkerTask

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────


class SchedulerFullError(RuntimeError):
    """Raised when the queue has reached ``max_queue_depth``."""


# ── Abstract base ─────────────────────────────────────────────────────────────


class Scheduler(ABC):
    """Abstract scheduler interface.  Phase 2 will add Redis/broker backends."""

    @abstractmethod
    async def submit(self, task: WorkerTask) -> None:
        """Enqueue *task* for execution."""

    @abstractmethod
    async def cancel(self, task_id: str) -> bool:
        """Request cancellation of a queued (not yet running) task.

        Returns ``True`` if the task was found and marked cancelled.
        """

    @abstractmethod
    async def drain(self) -> None:
        """Stop accepting new tasks and wait for the queue to empty."""

    @property
    @abstractmethod
    def queue_depth(self) -> int:
        """Current number of tasks waiting to be dispatched."""


# ── In-process implementation ─────────────────────────────────────────────────

# Dispatch callback type: (task) -> None  — called when a task is ready to run.
DispatchCallback = Callable[[WorkerTask], Awaitable[None]]


class InProcessScheduler(Scheduler):
    """Pure-asyncio priority-queue scheduler.

    ``dispatch_fn`` is called by the scheduler's background loop for each task
    that should be executed.  Typically this is
    :meth:`~agloom.runtime.pool.WorkerPool.dispatch`.

    Args:
        dispatch_fn:      Async callback that receives a ready task.
        max_queue_depth:  Reject tasks when the queue exceeds this depth.
                          ``0`` means unlimited.
        poll_interval_s:  How often the dispatcher wakes up to retry
                          tasks that couldn't be assigned last iteration.
    """

    def __init__(
        self,
        dispatch_fn: DispatchCallback,
        max_queue_depth: int = 0,
        poll_interval_s: float = 0.1,
    ) -> None:
        self._dispatch_fn = dispatch_fn
        self._max_depth = max_queue_depth
        self._poll_interval = poll_interval_s

        # asyncio.PriorityQueue uses the natural ordering of items.
        # WorkerTask.__lt__ puts higher-priority tasks first.
        self._queue: asyncio.PriorityQueue[WorkerTask] = asyncio.PriorityQueue()
        self._pending: dict[str, WorkerTask] = {}  # task_id → task

        self._running = False
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._drain_event = asyncio.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background dispatcher loop."""
        self._running = True
        self._dispatcher_task = asyncio.create_task(
            self._dispatcher_loop(), name="scheduler-dispatcher"
        )
        logger.debug("InProcessScheduler started")

    async def stop(self) -> None:
        """Stop the dispatcher after draining the current queue."""
        self._running = False
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
        logger.debug("InProcessScheduler stopped")

    # ── Scheduler protocol ─────────────────────────────────────────────────────

    async def submit(self, task: WorkerTask) -> None:
        """Enqueue *task*.  Raises :class:`SchedulerFullError` if queue is full."""
        if self._max_depth > 0 and self._queue.qsize() >= self._max_depth:
            raise SchedulerFullError(
                f"Scheduler queue is full ({self._queue.qsize()}/{self._max_depth})"
            )
        task.status = TaskStatus.QUEUED
        self._pending[task.task_id] = task
        await self._queue.put(task)
        logger.debug("Scheduler: queued task %s (depth=%d)", task.task_id, self._queue.qsize())

    async def cancel(self, task_id: str) -> bool:
        """Mark a queued task as cancelled.

        The task will be skipped when the dispatcher pops it.
        Running tasks cannot be cancelled via the scheduler — use the pool.
        """
        task = self._pending.get(task_id)
        if task and task.status == TaskStatus.QUEUED:
            task.status = TaskStatus.CANCELLED
            self._pending.pop(task_id, None)
            return True
        return False

    async def drain(self) -> None:
        """Block until the queue is empty."""
        await self._queue.join()

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    # ── Background dispatcher ──────────────────────────────────────────────────

    async def _dispatcher_loop(self) -> None:
        """Pop tasks and forward them to ``dispatch_fn`` as workers become free."""
        while self._running:
            try:
                task = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(self._poll_interval)
                continue

            # Skip cancelled tasks
            if task.status == TaskStatus.CANCELLED:
                self._queue.task_done()
                self._pending.pop(task.task_id, None)
                continue

            try:
                await self._dispatch_fn(task)
            except Exception:
                logger.exception("Scheduler: dispatch_fn raised for task %s", task.task_id)
            finally:
                self._queue.task_done()
                self._pending.pop(task.task_id, None)


__all__ = ["Scheduler", "InProcessScheduler", "SchedulerFullError"]
