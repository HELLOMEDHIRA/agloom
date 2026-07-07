"""Middleware: tool scratchpad digests and context budget compaction."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware

from ..context.compaction import compact_messages_for_budget
from ..context.errors import ContextBudgetExceededError
from ..context.tokens import estimate_messages_tokens
from ..context.tool_scratchpad import (
    MAX_TOOL_WIRE_CHARS,
    ToolScratchpad,
    build_tool_digest_async,
    is_recall_tool_name,
    serialize_tool_result,
)
from ..observability.context_events import emit_context_summarized
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
        max_wire_chars: int = MAX_TOOL_WIRE_CHARS,
        summarizer_model: Any | None = None,
    ) -> None:
        super().__init__()
        self._scratchpad = scratchpad
        self._digest_min_chars = max(500, digest_min_chars)
        self._max_wire_chars = max(1024, max_wire_chars)
        self._summarizer_model = summarizer_model

    def _should_digest(self, text: str) -> bool:
        return len(text) >= self._digest_min_chars or len(text) > self._max_wire_chars

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
        if not self._should_digest(text):
            return result
        art = self._scratchpad.store(tool_name or "tool", text, tool_call_id=tcid)
        digest = await build_tool_digest_async(
            ref_id=art.ref_id,
            tool_name=tool_name or "tool",
            full_text=text,
            summarizer_model=self._summarizer_model,
            max_wire_chars=self._max_wire_chars,
        )
        logger.info(
            f"[tool_scratchpad] stored {tool_name!r} ref={art.ref_id} "
            f"chars={len(text)} digest_chars={len(digest)} max_wire={self._max_wire_chars}"
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
        max_wire_chars: int = MAX_TOOL_WIRE_CHARS,
        event_queue: Any | None = None,
    ) -> None:
        super().__init__()
        self._context_window = max(4096, context_window)
        self._reserved_output = max(512, reserved_output)
        self._scratchpad = scratchpad
        self._compact_ratio = min(0.95, max(0.5, compact_ratio))
        self._max_wire_chars = max(1024, max_wire_chars)
        self._event_queue = event_queue

    def _input_budget(self) -> int:
        return max(2048, int(self._context_window * self._compact_ratio) - self._reserved_output)

    async def _compact_to_budget(
        self,
        messages: list[Any],
        budget: int,
        *,
        keep_recent_tool_rounds: int,
    ) -> tuple[list[Any], int]:
        compacted = compact_messages_for_budget(
            messages,
            self._scratchpad,
            target_input_tokens=budget,
            keep_recent_tool_rounds=keep_recent_tool_rounds,
            max_wire_chars=self._max_wire_chars,
        )
        return compacted, estimate_messages_tokens(compacted)

    async def awrap_model_call(
        self,
        request: Any,
        handler: Callable[[Any], Awaitable[Any]],
    ) -> Any:
        messages = list(request.messages or [])
        budget = self._input_budget()
        est = estimate_messages_tokens(messages)
        compacted_count = 0

        if est > budget and len(messages) > 3:
            compacted, new_est = await self._compact_to_budget(messages, budget, keep_recent_tool_rounds=2)
            if new_est < est:
                compacted_count += 1
                logger.warning(
                    f"[context_budget] compacted messages est_tokens {est} -> {new_est} "
                    f"(budget={budget} window={self._context_window} compacted_pass=1)"
                )
                messages = compacted
                est = new_est
                request = request.override(messages=compacted)

        if est > budget and len(messages) > 1:
            compacted, new_est = await self._compact_to_budget(messages, budget, keep_recent_tool_rounds=0)
            if new_est < est:
                compacted_count += 1
                logger.warning(
                    f"[context_budget] aggressive compact est_tokens {est} -> {new_est} "
                    f"(budget={budget} compacted_pass=2)"
                )
                messages = compacted
                est = new_est
                request = request.override(messages=compacted)

        if est > budget:
            await emit_context_summarized(
                scope="injection",
                tokens_before=est,
                tokens_after=est,
                event_queue=self._event_queue,
            )
            logger.error(
                f"[context_budget] pre-flight gate: est_tokens={est} budget={budget} "
                f"compacted_passes={compacted_count}"
            )
            raise ContextBudgetExceededError(estimated_tokens=est, budget=budget)

        if compacted_count:
            logger.info(
                f"[context_budget] est_tokens={est} budget={budget} compacted_count={compacted_count}"
            )

        return await handler(request)


def tool_context_settings_from_mapping(cfg: dict[str, Any]) -> dict[str, Any] | None:
    pad = cfg.get("_tool_scratchpad")
    if not isinstance(pad, ToolScratchpad):
        return None
    window = int(cfg.get("context_window_tokens") or 128_000)
    reserved = int(cfg.get("context_reserved_output_tokens") or 8192)
    summarizer = cfg.get("summarizer_model") or cfg.get("llm")
    return {
        "scratchpad": pad,
        "digest_min_chars": int(cfg.get("tool_digest_min_chars", 4000)),
        "context_window": window,
        "reserved_output": reserved,
        "compact_ratio": float(cfg.get("context_compact_ratio", 0.82)),
        "max_wire_chars": int(cfg.get("max_tool_wire_chars", MAX_TOOL_WIRE_CHARS)),
        "summarizer_model": summarizer,
        "event_queue": cfg.get("_event_queue"),
    }


def build_tool_context_middleware(settings: dict[str, Any]) -> tuple[Any, Any]:
    """Return (context_budget_middleware, tool_scratchpad_middleware)."""
    pad: ToolScratchpad = settings["scratchpad"]
    budget = ContextBudgetMiddleware(
        context_window=settings["context_window"],
        reserved_output=settings["reserved_output"],
        scratchpad=pad,
        compact_ratio=settings["compact_ratio"],
        max_wire_chars=settings.get("max_wire_chars", MAX_TOOL_WIRE_CHARS),
        event_queue=settings.get("event_queue"),
    )
    scratch = ToolScratchpadMiddleware(
        scratchpad=pad,
        digest_min_chars=settings["digest_min_chars"],
        max_wire_chars=settings.get("max_wire_chars", MAX_TOOL_WIRE_CHARS),
        summarizer_model=settings.get("summarizer_model"),
    )
    return budget, scratch
