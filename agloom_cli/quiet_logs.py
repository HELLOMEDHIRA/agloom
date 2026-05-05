"""Console log filtering for the agloom CLI (one-shot and REPL).

Third-party frameworks (HTTP clients, Groq SDK, LangGraph SQLite, etc.) stay off the console
below WARNING so the REPL **Thinking** / Assistant layout stays readable.

``--verbose`` turns on **agloom** package INFO/DEBUG (via ``create_agent(debug=True)``) but does
**not** re-enable framework trace noise — that requires using the library with your own handlers.

Filtering is applied to **root** handlers. Framework loggers are also capped at WARNING so a DEBUG
root level from verbose mode does not flood stderr with aiosqlite/httpx lines.
"""

from __future__ import annotations

import logging

_cli_noise_filter_installed = False

# Loggers that should never spam the CLI on INFO/DEBUG (even when --verbose / root DEBUG).
_FRAMEWORK_QUIET_PREFIXES: tuple[str, ...] = (
    "httpx",
    "httpcore",
    "urllib3",
    "openai",
    "groq",
    "anthropic",
    "langsmith",
    "langchain",
    "langgraph",
    "aiosqlite",
)


def _name_under_prefix(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _silence_framework_loggers() -> None:
    for prefix in _FRAMEWORK_QUIET_PREFIXES:
        logging.getLogger(prefix).setLevel(logging.WARNING)


def cli_reassert_framework_log_levels() -> None:
    """Re-apply framework logger caps after ``create_agent`` / ``configure_package_logging``.

    Verbose mode sets the root logger to DEBUG; child loggers under noisy namespaces must stay
    at WARNING or logs corrupt Rich ``Live`` (Thinking panel) on Windows terminals.
    """
    _silence_framework_loggers()


class CliConsoleNoiseFilter(logging.Filter):
    """Drop INFO/DEBUG from noisy frameworks always; drop agloom INFO/DEBUG unless verbose."""

    __slots__ = ("_app_verbose",)

    def __init__(self, *, app_verbose: bool) -> None:
        self._app_verbose = app_verbose
        super().__init__()

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 — logging API
        if record.levelno >= logging.WARNING:
            return True
        name = record.name
        for prefix in _FRAMEWORK_QUIET_PREFIXES:
            if _name_under_prefix(name, prefix):
                return False
        if not self._app_verbose and _name_under_prefix(name, "agloom"):
            return False
        return True


def install_cli_log_filter(*, verbose: bool) -> None:
    """Attach console filter and cap framework loggers. Call before ``create_agent``.

    With ``verbose=True``, agloom operational logs are shown; framework chatter is still hidden.
    """
    global _cli_noise_filter_installed
    if _cli_noise_filter_installed:
        return

    _silence_framework_loggers()

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)

    flt = CliConsoleNoiseFilter(app_verbose=verbose)
    for h in root.handlers:
        h.addFilter(flt)
    _cli_noise_filter_installed = True
