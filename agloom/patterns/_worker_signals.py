"""WorkerResult signal helpers — HALT vs FAILED semantics."""

from __future__ import annotations

from ..models import SignalType, WorkerResult


def worker_execution_failed(signal: SignalType) -> bool:
    """True only for retryable / operational worker failures (not user halt)."""
    return signal == SignalType.FAILED


def halted_worker_result(
    *,
    worker_id: str,
    task: str,
    output: str,
    error: str = "HALT_ALL",
) -> WorkerResult:
    """Build a worker row for L4 HALT_ALL skips and cancellations."""
    return WorkerResult(
        worker_id=worker_id,
        task=task,
        output=output,
        signal=SignalType.HALTED,
        error=error,
    )
