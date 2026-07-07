"""Failure classification for pattern terminal results."""

from __future__ import annotations

from typing import Any

from ..src.exception_utils import exception_indicates_transient_transport_error


def failure_class_for_error(
    error: str | None = None,
    *,
    exc: BaseException | None = None,
    kind: str = "execution",
) -> tuple[str, bool]:
    """Return ``(failure_class, retryable)`` for :class:`ExecutionResult`."""
    if exc is not None and exception_indicates_transient_transport_error(exc):
        return "transport", True
    text = (error or "").lower()
    if "timeout" in text or kind == "timeout":
        return "timeout", True
    if kind in ("planning", "worker", "tool_error", "transport", "timeout", "execution"):
        retryable = kind in ("transport", "timeout")
        return kind, retryable
    if "upstream" in text or "worker" in text:
        return "worker", False
    return kind, False


def exec_failure_kwargs(
    error: str | None = None,
    *,
    kind: str = "execution",
    exc: BaseException | None = None,
) -> dict[str, Any]:
    fc, retry = failure_class_for_error(error, kind=kind, exc=exc)
    return {"failure_class": fc, "retryable": retry}
