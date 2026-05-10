"""RuntimeNode — top-level assembly of the agloom-runtime execution platform.

A ``RuntimeNode`` is a self-contained execution unit:

    Scheduler ──► WorkerPool ──► Worker(s) ──► AGP events ──► transport

It is the single object that ``agloom-runtime serve`` creates and manages.
Application code (e.g. ``__main__.py``) only needs to interact with
:meth:`RuntimeNode.start`, :meth:`RuntimeNode.submit_invoke`, and
:meth:`RuntimeNode.stop`.

Phase 1 ships with:
  - One ``InProcessScheduler``
  - One ``WorkerPool`` with one or more ``LocalAIWorker`` instances
  - One ``InMemoryRegistry``

Phase 2 will add pluggable scheduler + registry backends; the RuntimeNode API
remains unchanged.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from ..protocol import AsyncSessionEmitter
from ..protocol.store import EventStore
from .pool import WorkerPool
from .registry import InMemoryRegistry, WorkerRegistry
from .scheduler import InProcessScheduler, Scheduler
from .workers.local import LocalAIWorker
from .workers.types import WorkerTask

logger = logging.getLogger(__name__)


class RuntimeNode:
    """Top-level runtime assembly.

    Typical usage::

        node = RuntimeNode.create_local(agent=my_agent, emitter=my_emitter)
        await node.start()

        # Dispatch a task
        await node.submit_invoke(
            prompt="What is 2+2?",
            thread="t_abc",
            session="s_xyz",
            emitter=session_emitter,
        )

        await node.stop()

    For multi-worker or remote-worker scenarios, use the lower-level APIs:
    ``node.pool.register_worker(...)`` and ``node.scheduler.submit(...)``.
    """

    def __init__(
        self,
        pool: WorkerPool,
        scheduler: Scheduler,
        registry: WorkerRegistry,
        store: EventStore | None = None,
    ) -> None:
        self.pool = pool
        self.scheduler = scheduler
        self.registry = registry
        self.store = store
        self._started = False

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def create_local(
        cls,
        agent: object,
        emitter: AsyncSessionEmitter,
        store: EventStore | None = None,
        worker_id: str | None = None,
        max_queue_depth: int = 0,
        health_interval_s: float = 30.0,
    ) -> RuntimeNode:
        """Convenience factory for single-node local execution (Phase 1 default).

        Creates one ``LocalAIWorker``, one ``InMemoryRegistry``, one
        ``InProcessScheduler``, and one ``WorkerPool``, all wired together.

        Args:
            agent:           A ``UnifiedAgent`` instance (or any object with
                             ``astream_events(prompt, thread_id=...)``.
            emitter:         The ``AsyncSessionEmitter`` for the active session.
            store:           Optional event store for replay/resume.
            worker_id:       Stable id for the worker (auto-generated if omitted).
            max_queue_depth: 0 = unlimited.
            health_interval_s: Frequency of worker health probes.
        """
        registry = InMemoryRegistry()

        pool = WorkerPool(
            emitter_factory=lambda: emitter,
            registry=registry,
            health_interval_s=health_interval_s,
        )

        # The scheduler's dispatch_fn delegates to the pool.
        # We create the scheduler first and wire it after pool is created.
        scheduler = InProcessScheduler(
            dispatch_fn=pool.dispatch,
            max_queue_depth=max_queue_depth,
        )

        # Create and register the default local AI worker
        wid = worker_id or f"w_local_{uuid4().hex[:8]}"
        worker = LocalAIWorker(worker_id=wid, agent=agent)
        # Workers are registered on start() — store them for deferred registration
        pool._pending_workers = [worker]  # type: ignore[attr-defined]

        return cls(pool=pool, scheduler=scheduler, registry=registry, store=store)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the scheduler and worker pool (including pending workers)."""
        # Register any workers that were queued before start()
        pending = getattr(self.pool, "_pending_workers", [])
        for worker in pending:
            await self.pool.register_worker(worker)
        self.pool.__dict__.pop("_pending_workers", None)

        await self.pool.start()
        if isinstance(self.scheduler, InProcessScheduler):
            await self.scheduler.start()

        self._started = True
        logger.info(
            "RuntimeNode started: %d worker(s), scheduler=%s",
            self.registry.worker_count,
            type(self.scheduler).__name__,
        )

    async def stop(self) -> None:
        """Drain the scheduler queue and stop all workers."""
        if isinstance(self.scheduler, InProcessScheduler):
            await self.scheduler.stop()
        await self.pool.stop()
        self._started = False
        logger.info("RuntimeNode stopped")

    # ── Task submission ────────────────────────────────────────────────────────

    async def submit_invoke(
        self,
        prompt: str,
        thread: str,
        session: str,
        emitter: AsyncSessionEmitter | None = None,
        priority: int = 0,
        timeout_ms: int | None = None,
        required_capabilities: list[str] | None = None,
    ) -> str:
        """Wrap a user prompt as an ``agent.invoke`` WorkerTask and schedule it.

        Returns the ``task_id`` so the caller can track or cancel the task.
        """
        task = WorkerTask(
            task_id=f"t_{uuid4().hex[:12]}",
            task_type="agent.invoke",
            payload={"prompt": prompt},
            session=session,
            thread=thread,
            priority=priority,
            timeout_ms=timeout_ms,
            required_capabilities=required_capabilities or ["agent:local"],
        )
        await self.scheduler.submit(task)
        return task.task_id

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task by id (queue or running)."""
        # Try scheduler first (queued but not yet dispatched)
        if await self.scheduler.cancel(task_id):
            return True
        # Fall back to pool (already dispatched and running)
        return await self.pool.cancel_task(task_id)

    # ── Observability ──────────────────────────────────────────────────────────

    @property
    def queue_depth(self) -> int:
        return self.scheduler.queue_depth

    @property
    def active_tasks(self) -> int:
        return self.pool.active_task_count

    async def health_snapshot(self) -> list:
        return await self.pool.get_health_snapshot()


__all__ = ["RuntimeNode"]
