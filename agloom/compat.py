"""Small LangChain/LangGraph compatibility helpers (kept out of :mod:`agloom.__init__`).

:func:`ensure_langchain_pending_deprecation_suppressed` is invoked from
:class:`~agloom.unified_agent.UnifiedAgent` and from runtime store setup; call it yourself
only if you touch LangGraph before constructing an agent.
"""

from __future__ import annotations

_LC_PENDING_DEPRECATION_FILTERED = False


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


__all__ = ["ensure_langchain_pending_deprecation_suppressed"]
