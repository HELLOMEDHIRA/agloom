"""Human-in-the-loop callback contract for library users.

``create_agent(..., user_callback=cb)`` receives asynchronous or synchronous
decisions through a single entry point. **Applications** (CLI, web UI, tests)
implement this callback; **agloom** does not render prompts.

Architecture — **two different gates** (do not conflate them):

1. **Tool execution gate** (:attr:`HITLEvent.TOOL_INTERRUPT_BEFORE`, plus pattern/worker
   interrupts). The model already produced a **valid** tool call (or the runtime reached
   a worker boundary). The human chooses **approve once**, **deny**, or **allowlist**
   so future runs skip prompts for that tool/pattern/worker. There is **no automatic
   “retry” loop for approval** — one interrupt → one decision → execute or skip.

2. **Invalid assistant message / provider rejection** (:attr:`HITLEvent.REACT_TOOL_USE_FAILED`).
   Some providers (e.g. Groq) return ``tool_use_failed`` when the **assistant text was
   not admissible as a tool call** — often prose instead of structured tool JSON.
   **Nothing is awaiting approval yet**: there is no named tool to allowlist until the
   model emits a proper tool call. Here the runtime may:

   - Run **automatic model-turn recovery**: inject a corrective ``HumanMessage`` and call
     the model again *without* involving you — this is **not** a second approval round;
     it is error correction before any executable tool exists.

   - Then, if recovery budget allows, call **your** callback so you can **stop** or
     **try another model turn** (product wording: “Retry / Stop”). That is orthogonal
     to the tool allowlist until a real tool appears.

If your product requires **human-first** behavior on the first provider rejection, set
``react_tool_use_failed_auto_retries_hitl`` to ``0`` so :attr:`HITLEvent.REACT_TOOL_USE_FAILED`
fires immediately with no silent model-turn recovery.

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

- **TOOL_INTERRUPT_BEFORE** — ``message`` is usually a ``dict`` from the ReAct middleware
  (``tool_name``, ``tool_call_id``, ``agent_name``, ``args``, ``detail``) or a legacy ``str``
  describing the tool call; return ``continue`` to run the tool or ``abort`` / ``no`` / ``cancel`` to skip.
- **PATTERN_INTERRUPT** — pattern gate; return truthy to continue or ``no`` to abort.
- **WORKER_INTERRUPT_BEFORE / AFTER** — parallel worker gates; ``continue`` or ``skip``.
- **CLARIFICATION_REQUEST** — ``message`` is ``dict`` or ``str``; return the user's reply.
- **REACT_TOOL_USE_FAILED** — provider rejected the assistant **message** (invalid /
  non-tool structured output). **Not** tool approve/deny; allowlist does not apply until
  a real tool call exists. Return values mean “another **model** attempt” vs “stop”;
  see :func:`normalize_react_tool_use_failed_decision`.

**Agent dict tuning** (optional):

- ``react_tool_use_failed_auto_retries_hitl`` — when ReAct **L2 HITL** is active, how many
  **silent model-turn recovery** steps (corrective message + new LLM call) run **before**
  :attr:`HITLEvent.REACT_TOOL_USE_FAILED` is raised (default: 2). These are **not**
  extra approval rounds — there is nothing to approve until the model emits a valid tool.
- ``react_tool_use_failed_user_rounds`` — how many times, after that, the callback may
  authorize another **batch** of recovery + model turns (default: 3).
"""

from __future__ import annotations

import inspect
from typing import Any, Literal

REACT_TOOL_USE_FAILED_USER_ROUNDS_KEY = "react_tool_use_failed_user_rounds"
DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS = 3

REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL_KEY = "react_tool_use_failed_auto_retries_hitl"
DEFAULT_REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL = 2


class HITLEvent:
    """Stable ``event_type`` strings for ``user_callback``.

    ``REACT_TOOL_USE_FAILED`` is provider rejection of the assistant *message* (invalid tool
    shape / prose), not the same as ``TOOL_INTERRUPT_BEFORE`` (approve a concrete tool run).
    """

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
    """Map callback result to continuing the ReAct loop vs stopping.

    ``retry`` means **another model turn** (after a corrective message), not re-running
    tool approval — no valid tool call existed for allowlisting yet.
    """
    text = str(raw).strip().lower()
    if text in ("retry", "continue", "accept", "allowlist", "yes", "1", "3", "true"):
        return "retry"
    return "abort"
