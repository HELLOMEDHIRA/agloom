"""WorkerPool — manages the lifecycle of workers and dispatches tasks.

The WorkerPool is the supervisor in the actor model:

    RuntimeNode → WorkerPool → Worker (actor)

Responsibilities:
- Start / stop workers on demand.
- Accept tasks from the Scheduler and assign them to available workers.
- Enforce per-task ``timeout_ms``.
- Retry failed tasks according to each task's :class:`~workers.types.RetryPolicy`.
- Run a background health-monitor that probes workers periodically and
  restarts unhealthy ones (up to ``max_restart_attempts``).
- Emit AGP ``worker.*`` events through the provided ``AsyncSessionEmitter``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from ..protocol import AsyncSessionEmitter
from .registry import InMemoryRegistry, WorkerRegistry
from .workers import BaseWorker
from .workers.types import TaskStatus, WorkerHealth, WorkerTask

logger = logging.getLogger(__name__)

# Factory type: () → AsyncSessionEmitter  (allows per-task emitter creation)
EmitterFactory = Callable[[], AsyncSessionEmitter]


class WorkerPool:
    """Manages a pool of workers and routes tasks to them.

    Args:
        emitter_factory:     Callable that returns a fresh ``AsyncSessionEmitter``
                             for each dispatched task (or a shared one for the session).
        registry:            WorkerRegistry backend.  Defaults to ``InMemoryRegistry``.
        health_interval_s:   How often to probe all workers for health.
        max_restart_attempts: Maximum consecutive restarts for a single unhealthy worker.
    """

    def __init__(
        self,
        emitter_factory: EmitterFactory,
        registry: WorkerRegistry | None = None,
        health_interval_s: float = 30.0,
        max_restart_attempts: int = 3,
    ) -> None:
        self._emitter_factory = emitter_factory
        self._registry: WorkerRegistry = registry or InMemoryRegistry()
        self._health_interval = health_interval_s
        self._max_restarts = max_restart_attempts

        self._restart_counts: dict[str, int] = {}  # worker_id → consecutive restart count
        self._running_tasks: dict[str, asyncio.Task[None]] = {}  # task_id → asyncio.Task
        self._health_monitor_task: asyncio.Task[None] | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the health monitor."""
        self._health_monitor_task = asyncio.create_task(
            self._health_monitor_loop(), name="worker-pool-health"
        )
        logger.debug("WorkerPool started (health_interval=%ss)", self._health_interval)

    async def stop(self) -> None:
        """Drain in-flight tasks and stop all workers."""
        if self._health_monitor_task:
            self._health_monitor_task.cancel()
            try:
                await self._health_monitor_task
            except asyncio.CancelledError:
                pass

        # Cancel in-flight tasks with a grace period
        if self._running_tasks:
            logger.info("WorkerPool stopping: cancelling %d running task(s)…", len(self._running_tasks))
            for t in self._running_tasks.values():
                t.cancel()
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)

        # Stop all workers
        stop_coros = [w.stop() for w in self._registry.all_workers()]
        await asyncio.gather(*stop_coros, return_exceptions=True)
        logger.debug("WorkerPool stopped")

    # ── Worker management ──────────────────────────────────────────────────────

    async def register_worker(self, worker: BaseWorker) -> None:
        """Add *worker* to the pool and call its ``start()`` lifecycle hook."""
        await worker.start()
        await self._registry.register(worker)

    async def deregister_worker(self, worker_id: str) -> None:
        """Stop and remove the worker identified by *worker_id*."""
        worker = self._registry.get(worker_id)
        if worker:
            await worker.stop()
            await self._registry.deregister(worker_id)

    # ── Task dispatch ──────────────────────────────────────────────────────────

    async def dispatch(self, task: WorkerTask) -> None:
        """Assign *task* to an available worker and execute it asynchronously.

        If no capable worker is available right now, back-off and retry until
        one becomes free.  This keeps the scheduler's dispatch_fn call from
        blocking — the actual retry polling is inside the asyncio task.
        """
        asyncio_task = asyncio.create_task(
            self._execute_with_retry(task), name=f"task-{task.task_id}"
        )
        self._running_tasks[task.task_id] = asyncio_task
        asyncio_task.add_done_callback(lambda _: self._running_tasks.pop(task.task_id, None))

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task.  Returns ``True`` if found and cancelled."""
        t = self._running_tasks.get(task_id)
        if t and not t.done():
            t.cancel()
            return True
        return False

    @property
    def active_task_count(self) -> int:
        return len(self._running_tasks)

    async def get_health_snapshot(self) -> list[WorkerHealth]:
        return await self._registry.get_health_snapshot()

    # ── Internal execution ─────────────────────────────────────────────────────

    async def _execute_with_retry(self, task: WorkerTask) -> None:
        """Poll for a capable worker, then execute the task with retry logic."""
        policy = task.retry_policy
        attempt = 0

        while True:
            # Find a capable, available worker
            worker = await self._wait_for_worker(task.required_capabilities)
            if worker is None:
                logger.error("WorkerPool: no capable worker found for task %s — giving up", task.task_id)
                task.status = TaskStatus.FAILED
                return

            emitter = self._emitter_factory()
            try:
                if task.timeout_ms:
                    await asyncio.wait_for(
                        worker.execute(task, emitter),
                        timeout=task.timeout_ms / 1_000,
                    )
                else:
                    await worker.execute(task, emitter)

                # Success
                return

            except TimeoutError:
                task.status = TaskStatus.TIMED_OUT
                task.finished_at = datetime.utcnow()
                attempt += 1
                error_code = "timeout"

            except asyncio.CancelledError:
                task.status = TaskStatus.CANCELLED
                task.finished_at = datetime.utcnow()
                raise

            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.finished_at = datetime.utcnow()
                attempt += 1
                error_code = "transient"
                logger.exception(
                    "WorkerPool: task %s failed on attempt %d: %s", task.task_id, attempt, exc
                )

            # Retry?
            if attempt > policy.max_retries or error_code not in policy.retryable_codes:
                logger.warning(
                    "WorkerPool: task %s exhausted retries (%d/%d)",
                    task.task_id, attempt, policy.max_retries,
                )
                return

            delay = policy.delay_for_attempt(attempt)
            logger.info(
                "WorkerPool: retrying task %s in %.1fs (attempt %d/%d)",
                task.task_id, delay, attempt, policy.max_retries,
            )
            await asyncio.sleep(delay)

    async def _wait_for_worker(
        self, required_capabilities: list[str], max_wait_s: float = 60.0
    ) -> BaseWorker | None:
        """Poll the registry until a capable worker is available or timeout."""
        waited = 0.0
        poll = 0.1
        while waited < max_wait_s:
            worker = self._registry.find_available(required_capabilities)
            if worker is not None:
                return worker
            await asyncio.sleep(poll)
            waited += poll
            poll = min(poll * 1.5, 2.0)  # gentle back-off
        return None

    # ── Health monitor ─────────────────────────────────────────────────────────

    async def _health_monitor_loop(self) -> None:
        """Periodically probe workers and restart unhealthy ones."""
        while True:
            await asyncio.sleep(self._health_interval)
            try:
                healths = await self._registry.get_health_snapshot()
            except Exception:
                logger.exception("WorkerPool: health probe failed")
                continue

            for health in healths:
                if not health.is_healthy:
                    logger.warning(
                        "WorkerPool: worker %s is %s — attempting restart",
                        health.worker_id, health.status.value,
                    )
                    await self._restart_worker(health.worker_id)

    async def _restart_worker(self, worker_id: str) -> None:
        consecutive = self._restart_counts.get(worker_id, 0)
        if consecutive >= self._max_restarts:
            logger.error(
                "WorkerPool: worker %s has crashed %d times — removing from pool",
                worker_id, consecutive,
            )
            await self.deregister_worker(worker_id)
            self._restart_counts.pop(worker_id, None)
            return

        worker = self._registry.get(worker_id)
        if worker is None:
            return

        self._restart_counts[worker_id] = consecutive + 1
        try:
            await worker.stop()
            await worker.start()
            logger.info(
                "WorkerPool: restarted worker %s (attempt %d/%d)",
                worker_id, consecutive + 1, self._max_restarts,
            )
            self._restart_counts[worker_id] = 0  # reset on successful restart
        except Exception:
            logger.exception("WorkerPool: failed to restart worker %s", worker_id)


__all__ = ["WorkerPool"]
