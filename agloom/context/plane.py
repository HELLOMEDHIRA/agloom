"""Context Plane — unified model-input assembly with automatic budget management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .summarize import summarize_text_for_budget
from .tokens import count_tokens
from .window import infer_context_window_tokens, reserved_output_tokens

_INPUT_FRACTION = 0.82
_DEFAULT_DIGEST_MIN = 500
_DEFAULT_DIGEST_MAX = 4000
_MAX_SUMMARIZE_PASSES = 5


@dataclass(frozen=True)
class ContextBudget:
    context_window: int
    reserved_output: int
    input_budget: int
    digest_min_chars: int


def compute_context_budget(
    llm: Any,
    *,
    model_spec: Any = None,
    context_window_tokens: int | None = None,
    compact_ratio: float = _INPUT_FRACTION,
    enable_thinking: bool | None = None,
) -> ContextBudget:
    ctx = context_window_tokens or infer_context_window_tokens(llm, model_spec)
    reserved = reserved_output_tokens(llm, context_window=ctx, enable_thinking=enable_thinking)
    input_budget = max(1024, int(ctx * compact_ratio) - reserved)
    digest = max(_DEFAULT_DIGEST_MIN, min(_DEFAULT_DIGEST_MAX, input_budget // 32))
    return ContextBudget(
        context_window=ctx,
        reserved_output=reserved,
        input_budget=input_budget,
        digest_min_chars=digest,
    )


def assemble_memory_context(
    text: str,
    *,
    budget: ContextBudget,
) -> tuple[str, bool]:
    """Return context for injection; never tail-chop — caller must summarize if over budget."""
    if not text:
        return "", False
    tokens = count_tokens(text)
    if tokens <= budget.input_budget:
        return text, False
    return text, True


async def ensure_memory_context_within_budget(
    text: str,
    *,
    budget: ContextBudget,
    summarizer_model: Any | None = None,
) -> str:
    """Summarize (never chop) until context fits the input budget or summarizer unavailable."""
    context, over = assemble_memory_context(text, budget=budget)
    if not over:
        return context
    if summarizer_model is None:
        return context
    tokens_before = count_tokens(context)
    compressed = context
    for _ in range(_MAX_SUMMARIZE_PASSES):
        if count_tokens(compressed) <= budget.input_budget:
            break
        prev = compressed
        compressed = await summarize_text_for_budget(compressed, summarizer_model=summarizer_model)
        if compressed == prev:
            break
    tokens_after = count_tokens(compressed)
    if tokens_after < tokens_before:
        try:
            from ..observability.context_events import emit_context_summarized

            await emit_context_summarized(
                scope="injection",
                tokens_before=tokens_before,
                tokens_after=tokens_after,
            )
        except Exception:
            pass
    return compressed


def internal_digest_min_chars(budget: ContextBudget) -> int:
    return budget.digest_min_chars
