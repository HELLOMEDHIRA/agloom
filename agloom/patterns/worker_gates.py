"""Sequential-pattern L4 helpers: drain signal_queue between steps without blocking the loop.

Used by blackboard (between knowledge-source runs). `drain_for_halt` uses `get_nowait` only
so the event loop stays free; it handles HALT_ALL and CLARIFICATION_REQUEST the same way
as the parallel HITL listener.
"""

from __future__ import annotations

import asyncio
from typing import Any

from ..hitl_contract import HITLEvent, call_user_callback
from ..logging_utils import get_logger
from ..models import Signal, SignalType

logger = get_logger(__name__)


def get_signal_queue(
    agent: dict,
    config: dict | None = None,
) -> asyncio.Queue | None:
    """
    Resolve the per-call signal_queue.
    Priority: agent["signal_queue"] → config["configurable"]["signal_queue"] → None
    """
    sq = agent.get("signal_queue")
    if sq is not None:
        return sq
    if config:
        sq = config.get("configurable", {}).get("signal_queue")
        if sq is not None:
            return sq
    return None


async def drain_for_halt(
    signal_queue: asyncio.Queue | None,
    caller_name: str = "Worker",
    user_callback: Any = None,
    clarification_queues: dict[str, asyncio.Queue] | None = None,
) -> bool:
    """
    Non-blocking drain of signal_queue between sequential worker steps.

    HALT_ALL:
      Logs warning, returns True immediately — caller must stop.

    CLARIFICATION_REQUEST (fully wired):
      1. Calls user_callback(HITLEvent.CLARIFICATION_REQUEST, {worker_id, question})
      2. Awaits user answer
      3. Routes answer → clarification_queues[worker_id]
      4. Worker's ask_for_clarification tool unblocks and continues
      Returns False — execution continues after answering.

    Returns False if queue is empty or None (normal step continuation).

    **Ordering:** All pending signals are drained with ``get_nowait()`` first; every
    ``HALT_ALL`` is handled before any ``CLARIFICATION_REQUEST`` so HALT is not stuck
    behind a blocking user prompt.
    """
    if signal_queue is None:
        return False

    batch: list[Any] = []
    while True:
        try:
            batch.append(signal_queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    halts = [
        raw
        for raw in batch
        if isinstance(raw, Signal) and raw.signal_type == SignalType.HALT_ALL
    ]
    if halts:
        sig = halts[0]
        logger.warning(
            f"[{caller_name}] L4 HALT_ALL — worker={sig.worker_id!r} — stopping execution "
            f"({len(halts)} HALT signal(s) in batch; {len(batch) - len(halts)} other item(s) discarded)."
        )
        return True

    for raw in batch:
        if not isinstance(raw, Signal):
            logger.warning(f"[{caller_name}] Ignoring non-Signal queue item: {type(raw).__name__!r}")
            continue
        signal = raw

        if signal.signal_type == SignalType.CLARIFICATION_REQUEST:
            logger.event(f"[{caller_name}] L4 CLARIFICATION_REQUEST from {signal.worker_id!r}: {signal.message!r}")

            if not user_callback:
                logger.warning(f"[{caller_name}] No user_callback — worker '{signal.worker_id}' will timeout in tool.")
                continue

            cqs = clarification_queues or {}
            cq = cqs.get(signal.worker_id)
            if cq is None:
                logger.warning(f"[{caller_name}] No clarification queue for '{signal.worker_id}' — answer dropped.")
                continue

            try:
                answer = await call_user_callback(
                    user_callback,
                    HITLEvent.CLARIFICATION_REQUEST,
                    {
                        "caller": caller_name,
                        "worker_id": signal.worker_id,
                        "question": signal.message,
                    },
                )
                logger.event(f"[{caller_name}] Clarification answered for '{signal.worker_id}': {str(answer)!r}")
                await cq.put(str(answer))

            except Exception as exc:
                logger.error(
                    f"[{caller_name}] user_callback raised during clarification: "
                    f"{exc} — sending fallback to '{signal.worker_id}'."
                )
                await cq.put(f"Clarification failed ({exc}). Proceed with best judgment.")

        else:
            logger.debug(f"[{caller_name}] Signal ignored: {signal.signal_type}")

    return False


async def await_with_halt_polling(
    main: asyncio.Task[Any],
    *,
    signal_queue: asyncio.Queue | None,
    caller_name: str = "Worker",
    user_callback: Any = None,
    clarification_queues: dict[str, asyncio.Queue] | None = None,
    poll_s: float = 0.25,
) -> tuple[Any | None, bool]:
    """Run ``main`` to completion, polling ``drain_for_halt`` on timeout slices.

    Returns ``(result, halted)``. On halt, ``main`` is cancelled and ``(None, True)`` is returned.
    """
    try:
        while not main.done():
            try:
                out = await asyncio.wait_for(asyncio.shield(main), timeout=poll_s)
                return (out, False)
            except asyncio.TimeoutError:
                if signal_queue and await drain_for_halt(
                    signal_queue,
                    caller_name=caller_name,
                    user_callback=user_callback,
                    clarification_queues=clarification_queues,
                ):
                    main.cancel()
                    try:
                        await main
                    except asyncio.CancelledError:
                        pass
                    return (None, True)
            except asyncio.CancelledError:
                raise
        return (main.result(), False)
    except asyncio.CancelledError:
        if not main.done():
            main.cancel()
            try:
                await main
            except asyncio.CancelledError:
                pass
        raise
