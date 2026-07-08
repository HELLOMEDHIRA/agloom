"""Failure classification for pattern terminal results."""

from __future__ import annotations

from typing import TypedDict

from ..src.exception_utils import exception_indicates_transient_transport_error


class ExecFailureKwargs(TypedDict, total=False):
    """Keyword arguments unpacked into :class:`~agloom.src.models.ExecutionResult`.

    ``total=False`` so an empty ``{}`` (success path) is a valid instance and unpacking is
    type-checked precisely at each call site.
    """

    failure_class: str | None
    retryable: bool


def failure_class_for_error(
    error: str | None = None,
    *,
    exc: BaseException | None = None,
    kind: str = "execution",
) -> tuple[str, bool]:
    """Return ``(failure_class, retryable)`` for :class:`ExecutionResult`."""
    if exc is not None and exception_indicates_transient_transport_error(exc):
        return "transport", True
    if isinstance(exc, Exception):
        from ..context.errors import ContextBudgetExceededError

        if isinstance(exc, ContextBudgetExceededError):
            return "context", False
    text = (error or "").lower()
    if "context budget exceeded" in text:
        return "context", False
    if "timeout" in text or kind == "timeout":
        return "timeout", True
    if kind in ("planning", "worker", "tool_error", "transport", "timeout", "execution", "context"):
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
) -> ExecFailureKwargs:
    fc, retry = failure_class_for_error(error, kind=kind, exc=exc)
    return {"failure_class": fc, "retryable": retry}
