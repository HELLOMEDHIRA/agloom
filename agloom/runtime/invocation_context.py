"""Per-invocation context for AGP runtime (stdio / WebSocket).

LangChain may execute sync tools on a thread pool; :mod:`contextvars` still propagate when
the executor copies the current context (Python 3.7+). We set bridge + emitter for each
:class:`~agloom.runtime.bridge.run_invocation` so CLI meta tools can resolve HITL and emit
auxiliary events on the correct forked emitter.
"""

from __future__ import annotations

import contextvars
from typing import Any

from .hitl import HITLBridge

_hitl_bridge_cv: contextvars.ContextVar[HITLBridge | None] = contextvars.ContextVar(
    "agloom_hitl_bridge",
    default=None,
)
_session_emitter_cv: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "agloom_session_emitter",
    default=None,
)


def attach_invocation_context(bridge: HITLBridge | None, emitter: Any) -> tuple[Any, Any]:
    """Return tokens for :func:`reset_invocation_context`."""
    return _hitl_bridge_cv.set(bridge), _session_emitter_cv.set(emitter)


def reset_invocation_context(tokens: tuple[Any, Any]) -> None:
    _hitl_bridge_cv.reset(tokens[0])
    _session_emitter_cv.reset(tokens[1])


def get_invocation_hitl_bridge() -> HITLBridge | None:
    return _hitl_bridge_cv.get()


def get_invocation_emitter() -> Any | None:
    return _session_emitter_cv.get()


async def runtime_hitl_user_callback(event_type: str, message: Any) -> Any:
    """``user_callback`` for shared agents (e.g. WebSocket) — delegates to the bridge for the
    active invocation (set via :func:`attach_invocation_context`)."""
    from ..hitl_contract import HITLEvent

    bridge = get_invocation_hitl_bridge()
    if bridge is None:
        if event_type == HITLEvent.CLARIFICATION_REQUEST:
            return ""
        return "abort"
    return await bridge.callback(event_type, message)


__all__ = [
    "attach_invocation_context",
    "get_invocation_emitter",
    "get_invocation_hitl_bridge",
    "reset_invocation_context",
    "runtime_hitl_user_callback",
]
