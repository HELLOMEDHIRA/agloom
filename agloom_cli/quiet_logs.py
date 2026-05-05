"""Console log filtering for the agloom CLI (one-shot and REPL).

``create_agent`` and friends use INFO for operational logs. Product-style CLIs keep those off
stdout unless ``--verbose`` (or ``create_agent(debug=True)`` for library use).

Filtering is applied to **root** handlers so it survives ``get_logger()`` resetting levels.
"""

from __future__ import annotations

import logging

_cli_noise_filter_installed = False


class CliFrameworkNoiseFilter(logging.Filter):
    """Hide INFO/DEBUG from common framework loggers; keep WARNING+ on the console."""

    _QUIET_PREFIXES: tuple[str, ...] = (
        "httpx",
        "httpcore",
        "urllib3",
        "openai",
        "groq",
        "anthropic",
        "langsmith",
        "langchain",
        "langgraph",
        "agloom",
    )

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 — logging API
        if record.levelno >= logging.WARNING:
            return True
        name = record.name
        for prefix in self._QUIET_PREFIXES:
            if name == prefix or name.startswith(prefix + "."):
                return False
        return True


def install_cli_log_filter(*, verbose: bool) -> None:
    """Attach noise filter to all existing root handlers; ensure root has at least one handler.

    Idempotent. Call at the start of ``_run`` **before** ``create_agent`` so startup INFO
    (e.g. ``create_agent: name=…``) is suppressed when ``verbose`` is false.
    """
    global _cli_noise_filter_installed
    if verbose or _cli_noise_filter_installed:
        return
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO)
    flt = CliFrameworkNoiseFilter()
    for h in root.handlers:
        h.addFilter(flt)
    _cli_noise_filter_installed = True
