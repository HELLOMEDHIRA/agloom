"""L2 HITL middleware — shared by react.py and worker.py to avoid circular imports."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, MutableSet
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from ..hitl_contract import HITLEvent, call_user_callback
from ..logging_utils import get_logger
from .hitl_read_file_dedupe import ReadFileHitlDeduper
from .hitl_tool_coalesce import CompositeToolHitlCoalescer

logger = get_logger(__name__)

# Tool names reserved / missing — never allowlist coalescer keys for these.
_L2_INVALID_ALLOWLIST_NAMES = frozenset({"", "unknown_tool", "unknown"})


class UserAbort(Exception):
    """Raised when user declines a gated tool call (e.g. skip/no).

    Mirrors L3 ``interrupt_before_workers`` skip: deliberate user gesture, not an
    agent/runtime failure — patterns return ``success=True`` with explanatory output/metadata.

    L2 skip decisions (``skip`` / ``no`` / ``abort`` / ``cancel``) align with L3 worker skip:
    the tool does not run, but the turn is not a hard execution failure.
    """


class ReactUserTurnToolChoiceMiddleware(AgentMiddleware):
    """After a user ``HumanMessage``, force ``tool_choice`` so the model emits structured tool calls."""

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
    """Pause before listed tools; ``"tools"`` in the interrupt list matches all tool names."""

    def __init__(
        self,
        interrupt_before_tools: list[str],
        user_callback: Callable,
        agent_name: str,
        tool_allowlist: MutableSet[str] | None = None,
        *,
        hitl_coalescer: CompositeToolHitlCoalescer | None = None,
    ) -> None:
        self.interrupt_before_tools = interrupt_before_tools
        self.user_callback = user_callback
        self.agent_name = agent_name
        self.tool_allowlist = tool_allowlist
        self._hitl_coalescer = hitl_coalescer or CompositeToolHitlCoalescer([ReadFileHitlDeduper()])

    @staticmethod
    def _extract_tool_call(request: Any) -> tuple[str, dict[str, Any], str | None]:
        """LangChain ``ToolCallRequest``: ``tool_call`` dict (>=1.x) or legacy ``name``/``args``/``tool_call_id``."""

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
            self._hitl_coalescer.record_approval(tool_name, tool_args)
            return await handler(request)

        if not should_pause:
            return await handler(request)

        if self._hitl_coalescer.should_skip_hitl(tool_name, tool_args):
            logger.event(
                f"{self.agent_name}[L2-HITL] Skipping HITL — coalesced with a recent approval "
                f"(tool-specific safe duplicate for `{tool_name}`)."
            )
            return await handler(request)

        logger.event(f"{self.agent_name}[L2-HITL] Pausing before tool '{tool_name}'")

        if raw_id is None:
            tool_call_id = uuid.uuid4().hex
        else:
            s = raw_id if isinstance(raw_id, str) else str(raw_id)
            tool_call_id = s.strip() or uuid.uuid4().hex
        payload: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "agent_name": self.agent_name,
            "args": tool_args,
            "detail": (
                f"Agent : {self.agent_name}\n"
                f"Tool  : {tool_name}\n"
                f"Args  : {tool_args}\n"
                "\n"
                "Each tool invocation requires approval unless the tool is on your session "
                "allowlist, or you allowlisted this tool and the runtime detects a safe subset "
                "duplicate (e.g. a smaller read_file limit on the same path — logged when it happens).\n"
                "In the agloom TUI: press Y = Accept once, N = Reject, A = Allowlist (this tool name "
                "for the rest of the session). Esc defaults to Reject."
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

        decision_norm = str(decision).strip().lower()
        if decision_norm in ("abort", "no", "skip", "cancel", "stop"):
            logger.event(f"{self.agent_name}[L2-HITL] User aborted tool '{tool_name}'.")
            raise UserAbort(f"User aborted tool call: {tool_name}")

        if decision_norm in ("allowlist", "a", "3"):
            if self.tool_allowlist is not None and tool_name and tool_name not in _L2_INVALID_ALLOWLIST_NAMES:
                self.tool_allowlist.add(tool_name)
            self._hitl_coalescer.record_approval(tool_name, tool_args)
            logger.event(
                f"{self.agent_name}[L2-HITL] Allowlisted — executing '{tool_name}' "
                f"(future calls skip prompt while allowlist is in effect)."
            )
            return await handler(request)

        logger.event(f"{self.agent_name}[L2-HITL] Approved — executing '{tool_name}'.")
        return await handler(request)
