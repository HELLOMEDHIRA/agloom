"""L2 HITL middleware — shared by react.py and worker.py to avoid circular imports."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from ..logging_utils import get_logger

logger = get_logger(__name__)


class UserAbort(Exception):
    """Raised when user aborts a tool call. Not a failure — treated as success=True."""


class HumanApprovalMiddleware(AgentMiddleware):
    """
    Intercepts tool calls inline in the ReAct loop for user approval.
    'tools' in interrupt list = wildcard. Supports sync and async callbacks.
    """

    def __init__(
        self,
        interrupt_before_tools: list[str],
        user_callback: Callable,
        agent_name: str,
    ) -> None:
        self.interrupt_before_tools = interrupt_before_tools
        self.user_callback = user_callback
        self.agent_name = agent_name

    async def awrap_tool_call(self, request: Any, handler: Callable) -> Any:
        tool_name: str = (
            getattr(request, "name", None)
            or getattr(request, "tool_name", None)
            or getattr(getattr(request, "tool", None), "name", None)
            or "unknown_tool"
        )

        should_pause: bool = bool(self.interrupt_before_tools) and (
            "tools" in self.interrupt_before_tools or tool_name in self.interrupt_before_tools
        )

        if not should_pause:
            return await handler(request)

        logger.event(f"{self.agent_name}[L2-HITL] Pausing before tool '{tool_name}'")

        try:
            decision = self.user_callback(
                "tool_interrupt_before",
                (
                    f"Agent : {self.agent_name}\n"
                    f"Tool  : {tool_name}\n"
                    f"Args  : {getattr(request, 'args', {})}\n"
                    f"\nType 'continue' to proceed or 'abort' to cancel."
                ),
            )
            if asyncio.iscoroutine(decision):
                decision = await decision
        except Exception as exc:
            logger.error(f"{self.agent_name}[L2-HITL] user_callback raised {exc!r} — defaulting to 'continue'.")
            decision = "continue"

        if str(decision).strip().lower() in ("abort", "no", "skip", "cancel", "stop"):
            logger.event(f"{self.agent_name}[L2-HITL] User aborted tool '{tool_name}'.")
            raise UserAbort(f"User aborted tool call: {tool_name}")

        logger.event(f"{self.agent_name}[L2-HITL] Approved — executing '{tool_name}'.")
        return await handler(request)
