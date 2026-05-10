"""Bridge: run an agent invocation and stream events to a :class:`SessionEmitter` as AGP.

Owns the lifecycle around a single invocation:

1. Open the session (``session.opened``).
2. Emit ``message.user`` with the prompt so the wire records the turn boundary even before
   the model speaks (replay tools depend on this).
3. For each :class:`AgentEvent` from ``agent.astream_events``, dispatch via :func:`translate`.
4. On normal completion, emit ``message.assistant`` if no terminal message was already sent,
   then ``session.closed`` with reason ``completed`` and a duration.
5. On exception, emit ``error.fatal`` with the exception's class + repr, then
   ``session.closed`` with reason ``error``.

The bridge is transport-agnostic: it talks only to the emitter. The emitter's writer decides
where the bytes land (stdout, a buffer for tests, a WebSocket queue later).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterable
from typing import Any, Protocol
from uuid import uuid4

from ..models import AgentEvent
from ..protocol import SessionEmitter
from .hitl import HITLBridge
from .invocation_context import attach_invocation_context, reset_invocation_context
from .translator import translate


class _SupportsAStreamEvents(Protocol):
    """Structural protocol for an agent (only what the bridge actually uses).

    ``UnifiedAgent`` satisfies this without modification; tests pass any object exposing
    ``astream_events(query, *, thread_id=…)``.
    """

    def astream_events(
        self,
        query: str | dict,
        *,
        thread_id: str | None = ...,
    ) -> AsyncIterable[AgentEvent]: ...


def new_session_id() -> str:
    """Mint a session id used for ``Envelope.session``. Opaque to consumers."""
    return f"sess_{uuid4().hex[:16]}"


async def run_invocation(
    *,
    agent: _SupportsAStreamEvents,
    prompt: str | dict,
    thread: str,
    emitter: SessionEmitter,
    hitl_bridge: HITLBridge | None = None,
) -> None:
    """Run one ``ainvoke``-equivalent over AGP.

    The emitter MUST already match ``thread`` (i.e. ``emitter.thread_id == thread``). The
    caller owns ``open()``; the bridge owns ``close()`` (so failures always close the session).

    Pass ``hitl_bridge`` when the runtime cancels tasks via ``task.cancel()`` so the bridge can
    distinguish ``prompt.cancelled(reason=user_aborted)`` from ``reason=shutdown`` using
    :meth:`HITLBridge.prepare_invocation_cancel`.
    """
    if not emitter.is_open:
        emitter.open()

    # Record the user prompt on the wire. Replay tools and frontends that join late can
    # reconstruct the full turn from this single event + the assistant stream that follows.
    user_text = prompt if isinstance(prompt, str) else _stringify_prompt(prompt)
    emitter.emit_message_user(content=user_text)
    _preview = user_text if len(user_text) <= 280 else f"{user_text[:277]}..."
    emitter.emit_prompt_requested(kind="user_turn", preview=_preview)
    emitter.emit_agent_busy(thread=thread)

    started = time.perf_counter()
    saw_message = False

    tokens = attach_invocation_context(hitl_bridge, emitter)
    try:
        try:
            async for event in agent.astream_events(prompt, thread_id=thread):
                if event.type in ("done", "answer", "message_assistant"):
                    saw_message = True
                translate(event, emitter)

        except asyncio.CancelledError:
            emitter.emit_agent_idle(thread=thread)
            # ``command.cancel`` vs runtime shutdown both cancel the task; callers distinguish via
            # :meth:`HITLBridge.prepare_invocation_cancel` immediately before ``task.cancel()``.
            elapsed = int((time.perf_counter() - started) * 1000)
            cancel_reason = (
                hitl_bridge.consume_invocation_cancel_reason(asyncio.current_task())
                if hitl_bridge
                else "user_aborted"
            )
            detail = "invocation_cancelled" if cancel_reason == "user_aborted" else "runtime_shutdown"
            emitter.emit_prompt_cancelled(reason=cancel_reason, detail=detail)
            emitter.close(reason=cancel_reason, duration_ms=elapsed)
            raise  # propagate so the runtime task stays cancelled (asyncio invariant)
        except Exception as exc:
            emitter.emit_agent_idle(thread=thread)
            # Two-event close path: emit ``error.fatal`` first (carries class + retryable hints) then
            # ``session.closed(reason="error")`` so consumers that subscribed only to ``error.*``
            # still get a complete failure record.
            elapsed = int((time.perf_counter() - started) * 1000)
            emitter.emit_error(
                severity="fatal",
                message=str(exc).strip() or repr(exc),
                error_class=type(exc).__name__,
                stage="invocation",
                retryable=False,
            )
            emitter.close(reason="error", duration_ms=elapsed, error=repr(exc))
            return

        emitter.emit_agent_idle(thread=thread)

        # If the stream ended without an explicit ``done``, the agent finished silently — synthesize
        # an empty assistant message so consumers get a clean turn boundary.
        if not saw_message:
            emitter.emit_message_assistant(content="", pattern=None)

        duration_ms = int((time.perf_counter() - started) * 1000)
        emitter.close(reason="completed", duration_ms=duration_ms)
    finally:
        reset_invocation_context(tokens)


def _stringify_prompt(prompt: dict) -> str:
    """Compact representation of a structured prompt for ``message.user.content``.

    Multi-modal / structured prompts (``{"input": "...", "images": [...]}``) are reduced to the
    primary text field when we can find one; otherwise we fall back to ``str(prompt)`` so the
    wire still carries *something* faithful.
    """
    for key in ("content", "input", "prompt", "query", "text", "message"):
        v = prompt.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return str(prompt)


async def run_invocation_to_writer(
    *,
    agent: _SupportsAStreamEvents,
    prompt: str | dict,
    thread: str | None = None,
    session: str | None = None,
    writer: Any = None,
    capabilities: list[str] | None = None,
) -> SessionEmitter:
    """High-level helper: build an emitter, run one invocation, return the emitter.

    Returned emitter has its final ``seq`` and ``is_open=False`` — useful for tests that want
    to inspect the last emitted event.
    """
    eff_thread = thread or f"thread_{uuid4().hex[:16]}"
    eff_session = session or new_session_id()
    emitter = SessionEmitter(
        session=eff_session,
        thread=eff_thread,
        writer=writer,
        capabilities=capabilities or [],
    )
    await run_invocation(agent=agent, prompt=prompt, thread=eff_thread, emitter=emitter)
    return emitter


__all__ = ["new_session_id", "run_invocation", "run_invocation_to_writer"]
