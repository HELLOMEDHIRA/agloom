"""L2 HITL middleware — shared by react.py and worker.py to avoid circular imports."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, MutableSet
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from ..hitl_contract import HITLEvent, call_user_callback
from ..logging_utils import get_logger

logger = get_logger(__name__)


class UserAbort(Exception):
    """Raised when user aborts a tool call. Not a failure — treated as success=True."""


class ReactUserTurnToolChoiceMiddleware(AgentMiddleware):
    """Align LangChain agent ``tool_choice`` with conversation state for ReAct.

    LangChain's ``create_agent`` defaults ``tool_choice=None`` on every model call. Providers
    such as Groq then allow plain-text assistant turns that *look* like tool output, which
    triggers ``tool_use_failed``. After a **HumanMessage** (user turn or retry nudge), set
    ``tool_choice="required"`` so the model must emit a structured tool call when tools exist.
    After **ToolMessage** / other turns, use ``tool_choice=None`` so the model can answer
    with plain text.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        user_turn_choice: str = "required",
    ) -> None:
        super().__init__()
        self._enabled = enabled
        self._user_turn_choice = user_turn_choice

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        if not self._enabled or not request.tools:
            return handler(request)
        last = request.messages[-1] if request.messages else None
        if isinstance(last, HumanMessage):
            return handler(request.override(tool_choice=self._user_turn_choice))
        return handler(request.override(tool_choice=None))

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        if not self._enabled or not request.tools:
            return await handler(request)
        last = request.messages[-1] if request.messages else None
        if isinstance(last, HumanMessage):
            return await handler(request.override(tool_choice=self._user_turn_choice))
        return await handler(request.override(tool_choice=None))


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
        tool_allowlist: MutableSet[str] | None = None,
    ) -> None:
        self.interrupt_before_tools = interrupt_before_tools
        self.user_callback = user_callback
        self.agent_name = agent_name
        self.tool_allowlist = tool_allowlist

    @staticmethod
    def _extract_tool_call(request: Any) -> tuple[str, dict[str, Any], str | None]:
        """Pull ``(tool_name, args, tool_call_id)`` from a LangChain ``ToolCallRequest``.

        Handles both LangChain >=1.x (``request.tool_call`` is a ``ToolCall`` dict with
        ``{"name", "args", "id"}`` plus ``request.tool`` for the BaseTool) and older shapes
        with flat ``request.name`` / ``request.args`` / ``request.tool_call_id``.
        """
        tc = getattr(request, "tool_call", None)
        if isinstance(tc, dict):
            name = tc.get("name") or ""
            args = tc.get("args") or {}
            tcid = tc.get("id")
        else:
            name = ""
            args = {}
            tcid = None
        if not name:
            name = (
                getattr(request, "name", None)
                or getattr(request, "tool_name", None)
                or getattr(getattr(request, "tool", None), "name", None)
                or ""
            )
        if not args:
            args = getattr(request, "args", {}) or {}
        if tcid is None:
            tcid = getattr(request, "tool_call_id", None)
        return name or "unknown_tool", dict(args) if isinstance(args, dict) else {}, tcid

    async def awrap_tool_call(self, request: Any, handler: Callable) -> Any:
        tool_name, tool_args, raw_id = self._extract_tool_call(request)

        should_pause: bool = bool(self.interrupt_before_tools) and (
            "tools" in self.interrupt_before_tools or tool_name in self.interrupt_before_tools
        )

        if should_pause and self.tool_allowlist is not None and tool_name in self.tool_allowlist:
            logger.event(f"{self.agent_name}[L2-HITL] Allowlisted — executing '{tool_name}' without prompt")
            return await handler(request)

        if not should_pause:
            return await handler(request)

        logger.event(f"{self.agent_name}[L2-HITL] Pausing before tool '{tool_name}'")

        tool_call_id = str(raw_id).strip() if raw_id is not None and str(raw_id).strip() else uuid.uuid4().hex
        payload: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "agent_name": self.agent_name,
            "args": tool_args,
            "detail": (
                f"Agent : {self.agent_name}\n"
                f"Tool  : {tool_name}\n"
                f"Args  : {tool_args}\n"
                f"\nType 'continue' to proceed or 'abort' to cancel."
            ),
        }

        try:
            decision = await call_user_callback(
                self.user_callback,
                HITLEvent.TOOL_INTERRUPT_BEFORE,
                payload,
            )
        except Exception as exc:
            logger.error(f"{self.agent_name}[L2-HITL] user_callback raised {exc!r} — aborting tool (not auto-approving).")
            raise UserAbort(f"HITL prompt failed: {exc}") from exc

        if str(decision).strip().lower() in ("abort", "no", "skip", "cancel", "stop"):
            logger.event(f"{self.agent_name}[L2-HITL] User aborted tool '{tool_name}'.")
            raise UserAbort(f"User aborted tool call: {tool_name}")

        logger.event(f"{self.agent_name}[L2-HITL] Approved — executing '{tool_name}'.")
        return await handler(request)
