"""Per-worker `ask_for_clarification` tool: signal → user_callback → answer on a dedicated queue.

Flow: tool enqueues CLARIFICATION_REQUEST; HITL routes the reply to
`clarification_queues[worker_id]` so concurrent workers (e.g. swarm) do not cross-talk.
The tool awaits `Queue.get` inside the tool node so the event loop can still run the listener.
"""

from __future__ import annotations

import asyncio

from langchain_core.tools import BaseTool
from langchain_core.tools import tool as make_tool

from ..logging_utils import get_logger
from ..models import Signal, SignalType

logger = get_logger(__name__)

# After timeout the worker gets a fallback string instead of hanging indefinitely.
CLARIFICATION_TIMEOUT_SECONDS: float = 300.0


def make_clarification_tool(
    worker_id: str,
    signal_queue: asyncio.Queue,
    clarification_queues: dict[str, asyncio.Queue],
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
    clarification_queues : shared dict — tool registers its queue here;
                           HITL listener reads from it to route answers
    """
    cq: asyncio.Queue[str] = asyncio.Queue()
    clarification_queues[worker_id] = cq

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
                timeout=CLARIFICATION_TIMEOUT_SECONDS,
            )
            logger.event(f"[Worker:{worker_id}] ▶ Clarification received — answer={answer!r}")
            return f"User clarification: {answer}"

        except TimeoutError:
            logger.warning(
                f"[Worker:{worker_id}] ⚠ Clarification timed out after "
                f"{CLARIFICATION_TIMEOUT_SECONDS}s — proceeding without answer."
            )
            return (
                "Clarification timed out — no user response received. "
                "Proceed with your best judgment based on available information."
            )

    return ask_for_clarification
