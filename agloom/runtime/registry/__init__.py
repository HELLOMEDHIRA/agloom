"""WorkerRegistry — discovery and capability lookup for workers.

The shipped implementation is :class:`InMemoryRegistry` (single process, no external services).
The abstract :class:`WorkerRegistry` interface allows alternative backends for larger deployments.

The registry is *read-only* from the scheduler's perspective.
Workers register/deregister themselves (or the WorkerPool does it on their behalf).
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Iterator

from ..workers import BaseWorker
from ..workers.types import WorkerHealth, WorkerStatus

logger = logging.getLogger(__name__)


# ── Abstract interface ────────────────────────────────────────────────────────


class WorkerRegistry(ABC):
    """Abstract worker registry.

    The registry maps ``worker_id`` → ``BaseWorker`` and provides capability-
    based lookup so the scheduler can find a worker that can run a given task.
    """

    @abstractmethod
    async def register(self, worker: BaseWorker) -> None:
        """Add *worker* to the registry."""

    @abstractmethod
    async def deregister(self, worker_id: str) -> None:
        """Remove the worker identified by *worker_id*."""

    @abstractmethod
    def get(self, worker_id: str) -> BaseWorker | None:
        """Return the worker for *worker_id*, or ``None``."""

    @abstractmethod
    def find_available(self, required_capabilities: list[str]) -> BaseWorker | None:
        """Return the first idle worker that satisfies *required_capabilities*.

        Returns ``None`` if no worker is currently available.
        """

    @abstractmethod
    def all_workers(self) -> Iterator[BaseWorker]:
        """Iterate over every registered worker."""

    @abstractmethod
    async def get_health_snapshot(self) -> list[WorkerHealth]:
        """Collect and return health probes from all registered workers."""

    @property
    @abstractmethod
    def worker_count(self) -> int:
        """Total number of registered workers."""


# ── In-memory implementation ──────────────────────────────────────────────────


class InMemoryRegistry(WorkerRegistry):
    """Thread-safe, in-process worker registry backed by a dict and asyncio.Lock."""

    def __init__(self) -> None:
        self._workers: dict[str, BaseWorker] = {}
        self._lock = asyncio.Lock()

    async def register(self, worker: BaseWorker) -> None:
        async with self._lock:
            if worker.worker_id in self._workers:
                logger.warning(
                    "Registry: worker %r already registered — replacing", worker.worker_id
                )
            self._workers[worker.worker_id] = worker
            logger.debug(
                "Registry: registered %r caps=%s", worker.worker_id, worker.capabilities
            )

    async def deregister(self, worker_id: str) -> None:
        async with self._lock:
            removed = self._workers.pop(worker_id, None)
            if removed:
                logger.debug("Registry: deregistered %r", worker_id)

    def get(self, worker_id: str) -> BaseWorker | None:
        return self._workers.get(worker_id)

    def find_available(self, required_capabilities: list[str]) -> BaseWorker | None:
        """Linear scan over registered workers (typical node counts are small)."""
        for worker in self._workers.values():
            if worker.is_available and worker.has_capabilities(required_capabilities):
                return worker
        return None

    def all_workers(self) -> Iterator[BaseWorker]:
        yield from self._workers.values()

    async def get_health_snapshot(self) -> list[WorkerHealth]:
        checks = [w.health_check() for w in self._workers.values()]
        results = await asyncio.gather(*checks, return_exceptions=True)
        healths: list[WorkerHealth] = []
        for worker, result in zip(self._workers.values(), results, strict=True):
            if isinstance(result, WorkerHealth):
                healths.append(result)
            else:
                healths.append(
                    WorkerHealth(
                        worker_id=worker.worker_id,
                        status=WorkerStatus.UNHEALTHY,
                        last_error=str(result),
                    )
                )
        return healths

    @property
    def worker_count(self) -> int:
        return len(self._workers)


__all__ = ["WorkerRegistry", "InMemoryRegistry"]
