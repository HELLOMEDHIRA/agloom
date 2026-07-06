"""Shared helpers for surfacing root causes from nested / grouped exceptions."""

from __future__ import annotations


def unwrap_exception(exc: BaseException) -> BaseException:
    """Return the deepest useful leaf from ``ExceptionGroup`` / cause chains."""
    current = exc
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        group_types: tuple[type, ...] = (ExceptionGroup, BaseExceptionGroup)
        if isinstance(current, group_types) and getattr(current, "exceptions", None):
            current = current.exceptions[0]
            continue
        cause = current.__cause__ or current.__context__
        if cause is not None and cause is not current:
            current = cause
            continue
        break
    return current


def format_exception_message(exc: BaseException, *, include_type: bool = True) -> str:
    """Human-readable message with ``ExceptionGroup`` / ``TaskGroup`` wrappers removed."""
    root = unwrap_exception(exc)
    msg = str(root).strip() or repr(root)
    if not include_type:
        return msg
    type_name = type(root).__name__
    if msg.startswith(f"{type_name}:") or msg.startswith(f"{type_name}("):
        return msg
    return f"{type_name}: {msg}"
