"""HITL bridge — translate agloom's ``user_callback`` contract into AGP ``hitl.*`` events.

The agloom core delivers HITL gates through a single ``user_callback(event_type, message)``
function (see :mod:`agloom.hitl_contract`). Library users plug in any UI here. For the AGP
runtime, the UI is *the wire*: every gate becomes a :class:`~agloom.protocol.HITLRequest`
event the frontend renders, and every ``command.hitl.respond`` from stdin resolves the
matching pending request so the agent can resume.

Wire flow for a tool gate::

    runtime → wire:   tool.call.start
    runtime → wire:   hitl.request           (request_id="hr_…", kind="tool_approval", …)
    frontend → wire:  command.hitl.respond   (request_id="hr_…", decision="accept")
    runtime → wire:   hitl.granted           (request_id="hr_…", actor="user")
    runtime → wire:   tool.call.result       (parent=tool.call.start.id)

The bridge owns a per-session ``request_id → asyncio.Future`` registry. Each
:meth:`HITLBridge.callback` invocation creates a future, emits the request, awaits the
future, then emits the outcome event. :meth:`HITLBridge.respond` resolves the future when an
inbound ``command.hitl.respond`` arrives.

**Per-invocation emitter routing**: when the serve loop runs multiple concurrent invocations
(each on a different ``thread_id``), each invocation has its own :class:`SessionEmitter` fork.
The bridge resolves which emitter to use by inspecting ``asyncio.current_task()`` — callers
register the mapping via :meth:`HITLBridge.bind_task_emitter` before scheduling the task.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal
from uuid import uuid4

from ..hitl_contract import HITLEvent
from ..protocol import HITLDecision, HITLKind, SessionEmitter

# Map agloom HITLEvent.* strings → AGP ``hitl.request.kind`` values. Keep the agloom contract
# stable: when a new HITLEvent type appears, add a row here (and a translator branch in
# :meth:`HITLBridge.callback` if its return-value semantics differ).
_KIND_BY_HITL_EVENT: dict[str, HITLKind] = {
    HITLEvent.TOOL_INTERRUPT_BEFORE: "tool_approval",
    HITLEvent.PATTERN_INTERRUPT: "pattern_approval",
    HITLEvent.WORKER_INTERRUPT_BEFORE: "worker_approval",
    HITLEvent.WORKER_INTERRUPT_AFTER: "worker_approval",
    HITLEvent.CLARIFICATION_REQUEST: "clarification",
    HITLEvent.REACT_TOOL_USE_FAILED: "react_recovery",
}

# Decision tokens accepted from ``command.hitl.respond.data.decision``. Anything else falls
# through to ``"reject"`` (safe default — never auto-approve on garbled input).
_VALID_DECISIONS: frozenset[str] = frozenset(
    {"accept", "reject", "allowlist", "retry", "stop", "timeout", "cancelled"}
)

# How HITL decisions translate back into the value the agloom callback contract expects.
# See ``agloom.hitl_contract`` for the per-event-type return-value rules.
_TOOL_GATE_RETURN: dict[HITLDecision, str] = {
    "accept": "continue",
    "allowlist": "continue",
    "reject": "abort",
    "stop": "abort",
    "timeout": "abort",
    "cancelled": "abort",
    "retry": "continue",  # not normally used for tool gates; tolerate gracefully
}

InvocationCancelReason = Literal["user_aborted", "shutdown"]
"""Why :func:`~agloom.runtime.bridge.run_invocation` was cancelled — drives ``prompt.cancelled``."""

_REACT_RECOVERY_RETURN: dict[HITLDecision, str] = {
    "retry": "retry",
    "accept": "retry",
    "allowlist": "retry",
    "reject": "abort",
    "stop": "abort",
    "timeout": "abort",
    "cancelled": "abort",
}


class HITLBridge:
    """Per-session HITL bridge between the agloom ``user_callback`` and the AGP wire.

    Construct one per :class:`SessionEmitter`. Pass :meth:`callback` as the agent's
    ``user_callback``. Feed inbound ``command.hitl.respond`` payloads to :meth:`respond`.

    **Concurrent-invocation support**: when the serve loop runs multiple concurrent
    invocations (each with their own ``SessionEmitter`` fork), call
    :meth:`bind_task_emitter` right after scheduling each invocation task. The bridge then
    routes HITL events to the correct per-invocation emitter by inspecting
    :func:`asyncio.current_task` at gate time, so two simultaneous agents can emit
    independent ``hitl.request`` events without cross-talk.
    """

    def __init__(self, emitter: SessionEmitter) -> None:
        self._default_emitter = emitter
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._kinds: dict[str, HITLKind] = {}  # request_id → kind
        self._req_task: dict[str, asyncio.Task[Any]] = {}  # request_id → owning task
        self._task_emitters: dict[asyncio.Task[Any], SessionEmitter] = {}
        self._task_thread: dict[asyncio.Task[Any], str] = {}  # task → thread_id
        self._task_cancel_reason: dict[asyncio.Task[Any], InvocationCancelReason] = {}
        self._lock = asyncio.Lock()

    # ── emitter routing ───────────────────────────────────────────────────

    def prepare_invocation_cancel(self, task: asyncio.Task[Any], *, reason: InvocationCancelReason) -> None:
        """Register why *task* is about to be cancelled.

        Call immediately before ``task.cancel()`` from the runtime loop so
        :func:`~agloom.runtime.bridge.run_invocation` can emit ``prompt.cancelled`` with
        ``reason=user_aborted`` vs ``reason=shutdown``.
        """
        self._task_cancel_reason[task] = reason

    def consume_invocation_cancel_reason(self, task: asyncio.Task[Any] | None) -> InvocationCancelReason:
        """Pop the cancel reason for *task* (default ``user_aborted``). Used inside ``run_invocation``."""
        if task is None:
            return "user_aborted"
        return self._task_cancel_reason.pop(task, "user_aborted")

    def bind_task_emitter(self, task: asyncio.Task[Any], emitter: SessionEmitter, thread: str = "") -> None:
        """Associate *task* with *emitter* so HITL events emitted within that task land on
        the correct per-invocation emitter.  The mapping is automatically cleaned up when
        the task finishes (via ``add_done_callback``).
        """
        self._task_emitters[task] = emitter
        if thread:
            self._task_thread[task] = thread

        def _cleanup(t: asyncio.Task[Any]) -> None:
            self._task_emitters.pop(t, None)
            self._task_thread.pop(t, None)
            self._task_cancel_reason.pop(t, None)

        task.add_done_callback(_cleanup)

    def _current_emitter(self) -> SessionEmitter:
        """Return the emitter bound to the current asyncio task (falls back to session default)."""
        task = asyncio.current_task()
        if task is not None:
            return self._task_emitters.get(task, self._default_emitter)
        return self._default_emitter

    # ── inbound from the agent (user_callback contract) ────────────────────

    async def callback(self, event_type: str, message: Any) -> Any:
        """Plug into ``create_agent(user_callback=…)``.

        Translates *event_type* into an AGP ``hitl.request``, awaits the matching response, and
        returns the value the agloom contract expects (``"continue"``/``"abort"``/free text/…).
        """
        emitter = self._current_emitter()
        kind = _KIND_BY_HITL_EVENT.get(event_type, "tool_approval")
        request_id = f"hr_{uuid4().hex[:16]}"
        params = _extract_request_params(message)

        if kind == "react_recovery":
            options, default = ["retry", "stop"], "stop"
        elif kind == "clarification":
            options, default = [], None
        else:
            options, default = ["accept", "reject", "allowlist"], "reject"

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        current_task = asyncio.current_task()
        async with self._lock:
            self._pending[request_id] = fut
            self._kinds[request_id] = kind
            if current_task is not None:
                self._req_task[request_id] = current_task

        request_evt = emitter.emit_hitl_request(
            request_id=request_id,
            kind=kind,
            detail=params.get("detail"),
            options=options,
            default=default,
            timeout_ms=params.get("timeout_ms"),
            agent_name=params.get("agent_name"),
            tool=params.get("tool_name"),
            tool_call_id=params.get("tool_call_id"),
            args=params.get("args"),
            worker=params.get("worker_id"),
            pattern=params.get("pattern"),
            question=params.get("question"),
        )

        timeout_s: float | None = None
        raw_timeout = params.get("timeout_ms")
        if isinstance(raw_timeout, (int, float)) and raw_timeout > 0:
            timeout_s = raw_timeout / 1000.0

        try:
            if timeout_s is not None:
                try:
                    response = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout_s)
                except TimeoutError:
                    # Auto-resolve as ``timeout`` so the wire gets a decision event
                    # and the agent proceeds on the safe default path (abort).
                    if not fut.done():
                        fut.set_result({"decision": "timeout", "text": None, "actor": "auto"})
                    response = await fut
            else:
                response = await fut
        except asyncio.CancelledError:
            emitter.emit_hitl_decision(
                request_id=request_id,
                decision="cancelled",
                actor="auto",
                detail="agent invocation cancelled before user responded",
                parent=request_evt.id,
            )
            raise
        finally:
            async with self._lock:
                self._pending.pop(request_id, None)
                self._kinds.pop(request_id, None)
                self._req_task.pop(request_id, None)

        decision: HITLDecision = response.get("decision", "reject")  # type: ignore[assignment]
        text: str | None = response.get("text")

        emitter.emit_hitl_decision(
            request_id=request_id,
            decision=decision,
            actor=str(response.get("actor") or "user"),
            text=text,
            parent=request_evt.id,
        )
        return _decision_to_callback_value(kind, decision, text)

    # ── inbound from the wire (command.hitl.respond) ────────────────────────

    def respond(self, request_id: str, decision: str, *, text: str | None = None, actor: str = "user") -> bool:
        """Resolve the pending future for *request_id*. Returns False if no such request is
        outstanding (stale/double response — emit nothing in that case)."""
        fut = self._pending.get(request_id)
        if fut is None or fut.done():
            return False
        normalized: HITLDecision = decision if decision in _VALID_DECISIONS else "reject"  # type: ignore[assignment]
        fut.set_result({"decision": normalized, "text": text, "actor": actor})
        return True

    def cancel_all(self) -> int:
        """Resolve every outstanding request as ``cancelled``. Returns count cancelled.

        Called on shutdown so any agent task awaiting an HITL gate unblocks promptly with a
        clean abort path.
        """
        cancelled = 0
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_result({"decision": "cancelled", "text": None, "actor": "auto"})
                cancelled += 1
        return cancelled

    def cancel_for_thread(self, thread: str) -> int:
        """Cancel only HITL requests belonging to *thread*. Returns count cancelled.

        Uses the task→thread mapping built by :meth:`bind_task_emitter` to identify which
        pending requests are owned by invocations on the given thread, avoiding accidental
        cancellation of unrelated concurrent sessions.
        """
        # Build inverse: task → request_ids for that task
        target_tasks = {task for task, t in self._task_thread.items() if t == thread}
        cancelled = 0
        for req_id, fut in list(self._pending.items()):
            if fut.done():
                continue
            owner = self._req_task.get(req_id)
            if owner in target_tasks:
                fut.set_result({"decision": "cancelled", "text": None, "actor": "auto"})
                cancelled += 1
        return cancelled

    @property
    def pending_count(self) -> int:
        return sum(1 for f in self._pending.values() if not f.done())


# ── helpers (module-level so they're trivially testable) ─────────────────────


_TOOL_LINE_RE = re.compile(r"Tool\s*:\s*(\S+)", re.IGNORECASE)


def _extract_request_params(message: Any) -> dict[str, Any]:
    """Pull the same fields the existing CLI parses out of ``user_callback(event, message)``.

    The agloom core's middleware payload shape is a dict like
    ``{"tool_name", "tool_call_id", "agent_name", "args", "detail"}`` for tool gates, or a plain
    string for legacy callers. Clarification payloads carry ``question`` and optional
    ``worker_id``. We forward what's there and leave missing fields as ``None`` so the
    emitter sends nothing.
    """
    if isinstance(message, dict):
        out = dict(message)
        # Some callers pass tool name only inside ``detail``. Don't lose it.
        if not out.get("tool_name") and isinstance(out.get("detail"), str):
            m = _TOOL_LINE_RE.search(out["detail"])
            if m:
                out["tool_name"] = m.group(1).strip()
        return out
    if isinstance(message, str):
        m = _TOOL_LINE_RE.search(message)
        return {"detail": message, "tool_name": m.group(1).strip() if m else None}
    return {"detail": str(message)}


def _decision_to_callback_value(kind: HITLKind, decision: HITLDecision, text: str | None) -> Any:
    """Map AGP decision → the value the agloom ``user_callback`` contract expects.

    See ``agloom.hitl_contract`` for the per-kind return-value rules.
    """
    if kind == "clarification":
        # Clarifications return free-text answers (or empty string if user cancelled).
        return text or ""
    if kind == "react_recovery":
        return _REACT_RECOVERY_RETURN.get(decision, "abort")
    # tool_approval / pattern_approval / worker_approval: continue vs abort.
    return _TOOL_GATE_RETURN.get(decision, "abort")


__all__ = ["HITLBridge", "InvocationCancelReason"]
