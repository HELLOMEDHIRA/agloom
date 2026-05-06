"""Human-in-the-loop callback contract for library users.

``create_agent(..., user_callback=cb)`` receives asynchronous or synchronous
decisions through a single entry point. **Applications** (CLI, web UI, tests)
implement this callback; **agloom** does not render prompts.

The contract limits **return values** (so the runtime knows whether to run a tool,
retry, etc.), not **what you do inside** the callback. You may run any real-time flow:
collect an OTP or MFA code, call an identity provider, wait on a WebSocket, enqueue
a ticket for a human manager, run policy checks—then return the outcome. For
**CLARIFICATION_REQUEST**, the return is an arbitrary string (answer, OTP digits,
free text—whatever your agent asked for). For **TOOL_INTERRUPT_BEFORE**, the return
is still ``continue`` vs ``abort`` after your verification logic succeeds or fails.

Callback signature::

    def user_callback(event_type: str, message: str | dict) -> Any: ...
    async def user_callback(event_type: str, message: str | dict) -> Any: ...

Use :class:`HITLEvent` for ``event_type`` instead of hard-coded strings.

- **TOOL_INTERRUPT_BEFORE** — ``message`` is a ``str`` describing the tool call;
  return ``continue`` to run the tool or ``abort`` / ``no`` / ``cancel`` to skip.
- **PATTERN_INTERRUPT** — pattern gate; return truthy to continue or ``no`` to abort.
- **WORKER_INTERRUPT_BEFORE / AFTER** — parallel worker gates; ``continue`` or ``skip``.
- **CLARIFICATION_REQUEST** — ``message`` is ``dict`` or ``str``; return the user's reply.
- **REACT_TOOL_USE_FAILED** — provider rejected the assistant turn before any tool ran
  (not the same as tool approval). Return ``retry`` or ``abort``; see
  :func:`normalize_react_tool_use_failed_decision` for accepted synonyms.

**Agent dict tuning** (optional):

- ``react_tool_use_failed_auto_retries_hitl`` — when **L2 HITL** is on (ReAct with
  ``user_callback`` + tool interrupts), how many **silent** ``tool_use_failed``
  retries run before ``REACT_TOOL_USE_FAILED`` is sent to the callback (default: 2).
  Without this, users would only see a prompt after the same long auto-retry budget
  as the non-HITL path.
- ``react_tool_use_failed_user_rounds`` — after that, how many times the callback
  may extend the run with a user-chosen retry (default: 3).
"""

from __future__ import annotations

import inspect
from typing import Any, Literal

REACT_TOOL_USE_FAILED_USER_ROUNDS_KEY = "react_tool_use_failed_user_rounds"
DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS = 3

REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL_KEY = "react_tool_use_failed_auto_retries_hitl"
DEFAULT_REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL = 2


class HITLEvent:
    """Stable ``event_type`` strings for ``user_callback``."""

    TOOL_INTERRUPT_BEFORE = "tool_interrupt_before"
    PATTERN_INTERRUPT = "pattern_interrupt"
    CLARIFICATION_REQUEST = "clarification_request"
    WORKER_INTERRUPT_BEFORE = "worker_interrupt_before"
    WORKER_INTERRUPT_AFTER = "worker_interrupt_after"
    REACT_TOOL_USE_FAILED = "react_tool_use_failed"


async def call_user_callback(callback: Any, event_type: str, message: Any) -> Any:
    """Invoke ``user_callback`` and await if it returned an awaitable.

    Both sync and async callbacks are supported per the contract above. Use this
    helper at every dispatch site so a sync callback never raises ``TypeError`` on
    ``await``.
    """
    result = callback(event_type, message)
    if inspect.isawaitable(result):
        result = await result
    return result


def normalize_react_tool_use_failed_decision(raw: Any) -> Literal["retry", "abort"]:
    """Map callback return value to a core decision (retry loop vs stop)."""
    text = str(raw).strip().lower()
    if text in ("retry", "continue", "accept", "allowlist", "yes", "1", "3", "true"):
        return "retry"
    return "abort"
