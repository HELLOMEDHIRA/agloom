"""Small LangChain/LangGraph compatibility helpers (kept out of :mod:`agloom.__init__`).

:func:`ensure_langchain_pending_deprecation_suppressed` is invoked from
:class:`~agloom.unified_agent.UnifiedAgent` and from runtime store setup; call it yourself
only if you touch LangGraph before constructing an agent.
"""

from __future__ import annotations

import sys
from typing import Any

_LC_PENDING_DEPRECATION_FILTERED = False
_STDIO_UTF8_CONFIGURED = False


def configure_stdio_utf8() -> None:
    """Best-effort UTF-8 for process stdout/stderr (AGP NDJSON on Windows cp1252 consoles)."""
    global _STDIO_UTF8_CONFIGURED
    if _STDIO_UTF8_CONFIGURED:
        return
    _STDIO_UTF8_CONFIGURED = True
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def safe_writer_write(writer: Any, text: str) -> None:
    """Write *text* without raising :exc:`UnicodeEncodeError` on narrow Windows encodings."""
    if writer is None:
        return
    try:
        writer.write(text)
        return
    except UnicodeEncodeError:
        pass
    buf = getattr(writer, "buffer", None)
    if buf is not None:
        buf.write(text.encode("utf-8", errors="replace"))
        return
    enc = getattr(writer, "encoding", None) or "utf-8"
    writer.write(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def ensure_langchain_pending_deprecation_suppressed() -> None:
    """Ignore ``LangChainPendingDeprecationWarning`` once per process (idempotent)."""
    global _LC_PENDING_DEPRECATION_FILTERED
    if _LC_PENDING_DEPRECATION_FILTERED:
        return
    _LC_PENDING_DEPRECATION_FILTERED = True
    try:
        import warnings

        from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

        warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)
    except ImportError:
        pass


__all__ = [
    "configure_stdio_utf8",
    "ensure_langchain_pending_deprecation_suppressed",
    "safe_writer_write",
]
