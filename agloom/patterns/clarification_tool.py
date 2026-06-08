"""Per-worker `ask_for_clarification` tool: signal → user_callback → answer on a dedicated queue.

Flow: tool enqueues CLARIFICATION_REQUEST; HITL routes the reply to
`clarification_queues[worker_id]` so concurrent workers (e.g. swarm) do not cross-talk.
The tool awaits `Queue.get` inside the tool node so the event loop can still run the listener.
"""

from __future__ import annotations

import asyncio
import os

from langchain_core.tools import BaseTool
from langchain_core.tools import tool as make_tool

from ..logging_utils import get_logger
from ..models import Signal, SignalType

logger = get_logger(__name__)

# After timeout the worker gets a fallback string instead of hanging indefinitely.
def _default_clarification_timeout() -> float:
    raw = os.environ.get("AGLOOM_CLARIFICATION_TIMEOUT_S", "300")
    try:
        return max(30.0, float(raw))
    except (TypeError, ValueError):
        return 300.0


CLARIFICATION_TIMEOUT_SECONDS: float = _default_clarification_timeout()


def make_clarification_tool(
    worker_id: str,
    signal_queue: asyncio.Queue,
    clarification_queues: dict[str, asyncio.Queue],
    *,
    timeout_seconds: float | None = None,
) -> BaseTool:
    """
    Create a per-worker ask_for_clarification tool.

    Side-effect at creation time:
      Registers clarification_queues[worker_id] = asyncio.Queue()
      The HITL listener routes user answers into this queue.

    Parameters
    ----------
    worker_id            : this worker's id (e.g. "worker-1", "researcher")
    signal_queue         : outbound queue — tool writes signal here
    clarification_queues : shared dict — one queue per ``worker_id``; reused across tool
                           recreation so in-flight clarifications are not orphaned.
    """
    cq = clarification_queues.get(worker_id)
    if cq is None:
        cq = asyncio.Queue()
        clarification_queues[worker_id] = cq
    wait_s = (
        timeout_seconds
        if timeout_seconds is not None
        else CLARIFICATION_TIMEOUT_SECONDS
    )

    @make_tool
    async def ask_for_clarification(question: str) -> str:
        """
        Pause and ask the user a clarifying question.
        Use this when the task is ambiguous, contradictory, or when you need
        information only the user can provide to proceed correctly.
        Returns the user's answer as a string — use it to continue the task.
        """
        logger.event(f"[Worker:{worker_id}] ⏸ CLARIFICATION_REQUEST — question={question!r}")

        await signal_queue.put(
            Signal(
                signal_type=SignalType.CLARIFICATION_REQUEST,
                worker_id=worker_id,
                message=question,
            )
        )

        try:
            answer = await asyncio.wait_for(
                cq.get(),
                timeout=wait_s,
            )
            logger.event(f"[Worker:{worker_id}] ▶ Clarification received — answer={answer!r}")
            return f"User clarification: {answer}"

        except TimeoutError:
            logger.warning(
                f"[Worker:{worker_id}] ⚠ Clarification timed out after "
                f"{wait_s}s — proceeding without answer."
            )
            return (
                "Clarification timed out — no user response received. "
                "Proceed with your best judgment based on available information."
            )

    return ask_for_clarification
