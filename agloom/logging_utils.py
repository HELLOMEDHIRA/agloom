"""
Thin wrapper around stdlib logging. Zero external deps.

Usage in every module::

    from .logging_utils import get_logger
    logger = get_logger(__name__)
    logger.event("classify", agent="ResearchAgent", pattern="SUPERVISOR")

Output modes (controlled by LOG_FORMAT env var):
    LOG_FORMAT=json → {"event":"classify","agent":"ResearchAgent",...}
    LOG_FORMAT=text → [ResearchAgent] classify | pattern=SUPERVISOR complexity=4
    (default=text)

Log levels:
    INFO  → always-on operational events (pattern routed, worker spawned, HITL fired)
    DEBUG → verbose detail (full QueryAnalysis, memory context, raw LLM output);
            activated by debug=True in create_agent() which calls
            configure_package_logging(debug=True)
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

_LOG_FORMAT_CACHE: str | None = None


def _log_format() -> str:
    """Return ``LOG_FORMAT`` env (default ``text``); read on first use, not at import."""
    global _LOG_FORMAT_CACHE
    if _LOG_FORMAT_CACHE is None:
        _LOG_FORMAT_CACHE = os.getenv("LOG_FORMAT", "text").lower()
    return _LOG_FORMAT_CACHE


_package_level: int = logging.INFO
_tracked_loggers: list[logging.Logger] = []
_tracked_logger_ids: set[int] = set()
_configured = False


def configure_package_logging(debug: bool = False) -> None:
    """Set agloom logger levels; install a root StreamHandler once if missing.

    Called from ``create_agent``. Most permissive level wins across agents.
    """
    global _package_level, _configured
    target = logging.DEBUG if debug else logging.INFO

    if target < _package_level:
        _package_level = target
        for lg in _tracked_loggers:
            lg.setLevel(_package_level)

    if not _configured:
        handler = logging.StreamHandler()
        if _log_format() == "json":
            handler.setFormatter(logging.Formatter("%(message)s"))
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)-5s %(name)s — %(message)s",
                    datefmt="%H:%M:%S",
                )
            )
        # Prefer the ``agloom`` namespace; propagate to root only when the app already configured it.
        root = logging.getLogger()
        pkg_root = logging.getLogger("agloom")
        if not pkg_root.handlers:
            pkg_root.addHandler(handler)
            pkg_root.setLevel(_package_level)
        pkg_root.propagate = bool(root.handlers)
        _configured = True


class _AgentLogger:
    """Structured events on top of a stdlib :class:`~logging.Logger`."""

    def __init__(self, stdlib_logger: logging.Logger) -> None:
        self._log = stdlib_logger

    def _emit(self, level: int, event: str, **fields: Any) -> None:
        if not self._log.isEnabledFor(level):
            return

        if _log_format() == "json":
            payload = {"event": event, "ts": time.time(), **fields}
            self._log.log(level, json.dumps(payload, default=str))
        else:
            prefix = f"[{fields.pop('agent', '')}] " if "agent" in fields else ""
            pairs = " | ".join(f"{k}={v}" for k, v in fields.items())
            msg = f"{prefix}{event}" + (f" | {pairs}" if pairs else "")
            self._log.log(level, msg)

    def event(self, name: str, **fields: Any) -> None:
        """INFO-level operational event — always emitted in production."""
        self._emit(logging.INFO, name, **fields)

    def info(self, name: str, **fields: Any) -> None:
        """Alias for event() — stdlib-compatible INFO-level logging."""
        self._emit(logging.INFO, name, **fields)

    def debug(self, name: str, **fields: Any) -> None:
        """DEBUG-level verbose detail — only when logging.DEBUG is active."""
        self._emit(logging.DEBUG, name, **fields)

    def warning(self, name: str, **fields: Any) -> None:
        self._emit(logging.WARNING, name, **fields)

    def error(self, name: str, **fields: Any) -> None:
        self._emit(logging.ERROR, name, **fields)

    def log_at(self, level: int, name: str, **fields: Any) -> None:
        """Emit at a dynamic stdlib level (e.g. logging.WARNING)."""
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
    """Drop-in replacement for logging.getLogger() across the package."""
    stdlib_logger = logging.getLogger(name)
    stdlib_logger.setLevel(_package_level)
    sid = id(stdlib_logger)
    if sid not in _tracked_logger_ids:
        _tracked_logger_ids.add(sid)
        _tracked_loggers.append(stdlib_logger)
    return _AgentLogger(stdlib_logger)
