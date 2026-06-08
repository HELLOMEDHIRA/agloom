"""
Structured logging via structlog (stdlib integration).

Usage in every module::

    from .logging_utils import get_logger
    logger = get_logger(__name__)
    logger.event("classify", agent="ResearchAgent", pattern="SUPERVISOR")

Output modes (``LOG_FORMAT`` env var):

    ``json`` → one JSON object per line (log aggregators)
    ``text`` → human-readable console output (default)

Levels: ``configure_package_logging(debug=True)`` from ``create_agent()`` sets DEBUG on
all package loggers obtained via :func:`get_logger`.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import structlog

_LOG_FORMAT_CACHE: str | None = None

_package_level: int = logging.INFO
_tracked_loggers: list[logging.Logger] = []
_tracked_logger_ids: set[int] = set()
_configured = False


def _log_format() -> str:
    """Return ``LOG_FORMAT`` env (default ``text``); read on first use, not at import."""
    global _LOG_FORMAT_CACHE
    if _LOG_FORMAT_CACHE is None:
        _LOG_FORMAT_CACHE = os.getenv("LOG_FORMAT", "text").lower()
    return _LOG_FORMAT_CACHE


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", key="ts"),
        structlog.stdlib.ExtraAdder(),
    ]


def _final_renderer() -> Any:
    if _log_format() == "json":
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer(colors=False, pad_event=24)


def configure_package_logging(debug: bool = False) -> None:
    """Set agloom logger levels; configure structlog + a StreamHandler once.

    Called from ``create_agent``. Most permissive level wins across agents.
    """
    global _package_level, _configured
    target = logging.DEBUG if debug else logging.INFO

    if target < _package_level:
        _package_level = target
        for lg in _tracked_loggers:
            lg.setLevel(_package_level)

    if not _configured:
        shared = _shared_processors()
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                _final_renderer(),
            ],
        )
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)

        root = logging.getLogger()
        pkg_root = logging.getLogger("agloom")
        if not pkg_root.handlers:
            pkg_root.addHandler(handler)
            pkg_root.setLevel(_package_level)
        pkg_root.propagate = bool(root.handlers)

        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                *shared,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        _configured = True


_LEVEL_TO_METHOD: dict[int, str] = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warning",
    logging.ERROR: "error",
    logging.CRITICAL: "critical",
}


class _AgentLogger:
    """Thin facade over :class:`structlog.stdlib.BoundLogger` for stable call sites."""

    def __init__(self, name: str, stdlib_logger: logging.Logger) -> None:
        self._stdlib = stdlib_logger
        self._log = structlog.stdlib.get_logger(name)

    def _emit(self, level: int, event: str, **fields: Any) -> None:
        if not self._stdlib.isEnabledFor(level):
            return
        method = _LEVEL_TO_METHOD.get(level, "info")
        log_fn = getattr(self._log, method)
        if fields:
            log_fn(event, **fields)
        else:
            log_fn(event)

    def event(self, name: str, **fields: Any) -> None:
        """INFO-level operational event — always emitted in production."""
        self._emit(logging.INFO, name, **fields)

    def info(self, name: str, **fields: Any) -> None:
        """Alias for :meth:`event` — stdlib-compatible INFO-level logging."""
        self._emit(logging.INFO, name, **fields)

    def debug(self, name: str, **fields: Any) -> None:
        """DEBUG-level verbose detail — only when logging.DEBUG is active."""
        self._emit(logging.DEBUG, name, **fields)

    def warning(self, name: str, **fields: Any) -> None:
        self._emit(logging.WARNING, name, **fields)

    def error(self, name: str, **fields: Any) -> None:
        self._emit(logging.ERROR, name, **fields)

    def log_at(self, level: int, name: str, **fields: Any) -> None:
        """Emit at a dynamic stdlib level (e.g. ``logging.WARNING``)."""
        self._emit(level, name, **fields)

    def timed(self, name: str, **fields: Any):
        """Context manager: emit *name* with ``elapsed_ms`` (and ``success``) on exit."""
        return _TimedEvent(self, name, fields)


class _TimedEvent:
    def __init__(self, logger: _AgentLogger, name: str, fields: dict) -> None:
        self._logger = logger
        self._name = name
        self._fields = fields
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, *_):
        elapsed_ms = round((time.perf_counter() - self._start) * 1000, 1)
        self._logger.event(
            self._name,
            elapsed_ms=elapsed_ms,
            success=exc_type is None,
            **self._fields,
        )


def get_logger(name: str) -> _AgentLogger:
    """Drop-in logger for the package; backed by structlog + stdlib."""
    stdlib_logger = logging.getLogger(name)
    stdlib_logger.setLevel(_package_level)
    sid = id(stdlib_logger)
    if sid not in _tracked_logger_ids:
        _tracked_logger_ids.add(sid)
        _tracked_loggers.append(stdlib_logger)
    return _AgentLogger(name, stdlib_logger)
