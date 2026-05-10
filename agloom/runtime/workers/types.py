"""Worker task and health data models for agloom-runtime.

These are pure data classes — no I/O, no async, no runtime dependencies.
They are the shared vocabulary between the Scheduler, WorkerPool, and Workers.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ── Enumerations ──────────────────────────────────────────────────────────────


class WorkerType(str, enum.Enum):
    """Broad category of a worker.  Used for registry filtering and metrics."""

    LOCAL_AI = "local_ai"
    TOOL = "tool"
    SUBPROCESS = "subprocess"
    REMOTE_HTTP = "remote_http"
    REMOTE_WS = "remote_ws"
    RAY = "ray"
    GPU_INFERENCE = "gpu_inference"
    EMBEDDING = "embedding"
    BROWSER = "browser"
    CUSTOM = "custom"


class TaskStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class WorkerStatus(str, enum.Enum):
    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    DRAINING = "draining"  # no new tasks; finishing in-flight
    STOPPED = "stopped"
    UNHEALTHY = "unhealthy"


# ── Retry policy ──────────────────────────────────────────────────────────────


@dataclass
class RetryPolicy:
    """Controls automatic retry behaviour for failed tasks.

    ``retryable_codes`` is matched against the ``error_code`` field on a
    :class:`TaskResult`.  Pass ``retryable_codes={"*"}`` to retry on any error.
    """

    max_retries: int = 3
    backoff_ms: int = 1_000
    backoff_multiplier: float = 2.0
    retryable_codes: set[str] = field(
        default_factory=lambda: {"timeout", "transient", "resource_unavailable"}
    )

    def delay_for_attempt(self, attempt: int) -> float:
        """Return the sleep duration (seconds) before retry *attempt* (1-indexed)."""
        delay_ms = self.backoff_ms * (self.backoff_multiplier ** (attempt - 1))
        return delay_ms / 1_000


_DEFAULT_RETRY = RetryPolicy()


# ── WorkerTask ────────────────────────────────────────────────────────────────


@dataclass
class WorkerTask:
    """A unit of work dispatched by the Scheduler to a Worker.

    The *required_capabilities* list is matched against a worker's capability
    tags.  All required capabilities must be present for assignment.

    *priority* is negated before insertion into :class:`asyncio.PriorityQueue`
    (higher number = higher priority = popped first).
    """

    task_id: str
    task_type: str          # e.g. "agent.invoke", "tool.execute", "embed"
    payload: dict[str, Any]

    # AGP routing keys
    session: str
    thread: str

    # Scheduling hints
    priority: int = 0       # 0 = normal | 1 = high | -1 = background
    timeout_ms: int | None = None
    required_capabilities: list[str] = field(default_factory=list)
    retry_policy: RetryPolicy = field(default_factory=lambda: _DEFAULT_RETRY)

    # Lifecycle bookkeeping (set by WorkerPool, not by callers)
    status: TaskStatus = TaskStatus.QUEUED
    attempt: int = 0
    assigned_worker_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # ── PriorityQueue ordering ──────────────────────────────────────────────

    def __lt__(self, other: WorkerTask) -> bool:
        """Higher priority tasks sort first; ties broken by creation time."""
        if self.priority != other.priority:
            return self.priority > other.priority  # higher value = higher priority
        return self.created_at < other.created_at

    def __le__(self, other: WorkerTask) -> bool:
        return self == other or self < other

    def duration_ms(self) -> int | None:
        """Wall-clock duration in ms; ``None`` if not yet finished."""
        if self.started_at and self.finished_at:
            return int((self.finished_at - self.started_at).total_seconds() * 1_000)
        return None


# ── TaskResult ────────────────────────────────────────────────────────────────


@dataclass
class TaskResult:
    """Outcome reported by a Worker after executing a WorkerTask."""

    task_id: str
    status: TaskStatus
    error_code: str | None = None
    error_message: str | None = None
    output_preview: str | None = None


# ── WorkerHealth ──────────────────────────────────────────────────────────────


@dataclass
class WorkerHealth:
    """Snapshot of a worker's health at the time of a probe."""

    worker_id: str
    status: WorkerStatus
    active_tasks: int = 0
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    uptime_s: float = 0.0
    last_error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.status not in (WorkerStatus.UNHEALTHY, WorkerStatus.STOPPED)

    @property
    def is_available(self) -> bool:
        return self.status == WorkerStatus.IDLE


__all__ = [
    "WorkerType",
    "TaskStatus",
    "WorkerStatus",
    "RetryPolicy",
    "WorkerTask",
    "TaskResult",
    "WorkerHealth",
]
