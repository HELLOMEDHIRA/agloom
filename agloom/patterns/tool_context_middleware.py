"""Middleware: tool scratchpad digests and context budget compaction."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from ..context.compaction import compact_messages_for_budget
from ..context.tokens import estimate_messages_tokens
from ..context.tool_scratchpad import (
    ToolScratchpad,
    build_tool_digest,
    is_recall_tool_name,
    serialize_tool_result,
)
from ..src.logging_utils import get_logger
from .middleware import HumanApprovalMiddleware

logger = get_logger(__name__)


class ToolScratchpadMiddleware(AgentMiddleware):
    """Store large tool outputs off-thread; return digests to the model."""

    def __init__(
        self,
        scratchpad: ToolScratchpad,
        *,
        digest_min_chars: int = 4000,
    ) -> None:
        super().__init__()
        self._scratchpad = scratchpad
        self._digest_min_chars = max(500, digest_min_chars)

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        tool_name, _, tcid = HumanApprovalMiddleware._extract_tool_call(request)
        result = await handler(request)
        if is_recall_tool_name(tool_name):
            return result
        text = serialize_tool_result(result)
        if len(text) < self._digest_min_chars:
            return result
        art = self._scratchpad.store(tool_name or "tool", text, tool_call_id=tcid)
        digest = build_tool_digest(ref_id=art.ref_id, tool_name=tool_name or "tool", full_text=text)
        logger.info(
            f"[tool_scratchpad] stored {tool_name!r} ref={art.ref_id} "
            f"chars={len(text)} digest_chars={len(digest)}"
        )
        return digest


class ContextBudgetMiddleware(AgentMiddleware):
    """Compact older tool messages when estimated input nears the context window."""

    def __init__(
        self,
        *,
        context_window: int,
        reserved_output: int,
        scratchpad: ToolScratchpad,
        compact_ratio: float = 0.82,
    ) -> None:
        super().__init__()
        self._context_window = max(4096, context_window)
        self._reserved_output = max(512, reserved_output)
        self._scratchpad = scratchpad
        self._compact_ratio = min(0.95, max(0.5, compact_ratio))

    def _input_budget(self) -> int:
        return max(2048, int(self._context_window * self._compact_ratio) - self._reserved_output)

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        messages = list(request.messages or [])
        budget = self._input_budget()
        est = estimate_messages_tokens(messages)
        if est > budget and len(messages) > 3:
            compacted = compact_messages_for_budget(
                messages,
                self._scratchpad,
                target_input_tokens=budget,
            )
            new_est = estimate_messages_tokens(compacted)
            if new_est < est:
                logger.warning(
                    f"[context_budget] compacted messages est_tokens {est} -> {new_est} "
                    f"(budget={budget} window={self._context_window})"
                )
                request = request.override(messages=compacted)
        return await handler(request)


def tool_context_settings_from_mapping(cfg: dict[str, Any]) -> dict[str, Any] | None:
    if cfg.get("tool_scratchpad") is False:
        return None
    pad = cfg.get("_tool_scratchpad")
    if not isinstance(pad, ToolScratchpad):
        return None
    window = int(cfg.get("context_window_tokens") or 128_000)
    reserved = int(cfg.get("context_reserved_output_tokens") or 8192)
    return {
        "scratchpad": pad,
        "digest_min_chars": int(cfg.get("tool_digest_min_chars", 4000)),
        "context_window": window,
        "reserved_output": reserved,
        "compact_ratio": float(cfg.get("context_compact_ratio", 0.82)),
    }


def build_tool_context_middleware(settings: dict[str, Any]) -> tuple[Any, Any]:
    """Return (context_budget_middleware, tool_scratchpad_middleware)."""
    pad: ToolScratchpad = settings["scratchpad"]
    budget = ContextBudgetMiddleware(
        context_window=settings["context_window"],
        reserved_output=settings["reserved_output"],
        scratchpad=pad,
        compact_ratio=settings["compact_ratio"],
    )
    scratch = ToolScratchpadMiddleware(
        scratchpad=pad,
        digest_min_chars=settings["digest_min_chars"],
    )
    return budget, scratch
