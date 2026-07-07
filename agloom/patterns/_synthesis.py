"""Shared pattern synthesis runner."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..src.models import ExecutionResult, QueryAnalysis


async def run_pattern_synthesis(
    agent: dict[str, Any],
    config: dict | None,
    query: str,
    analysis: QueryAnalysis,
    *,
    worker_outputs: list[str],
    prompt: str,
) -> ExecutionResult:
    """Run a single synthesis LLM call over worker outputs."""
    from ..src.llm_streaming import stream_or_invoke_llm

    combined = "\n\n---\n\n".join(o for o in worker_outputs if o)
    llm = agent.get("llm")
    raw_timeout = (
        config.get("llm_timeout") if config is not None else None
    ) or agent.get("llm_timeout", 120.0)
    try:
        timeout = max(float(raw_timeout), 1.0)
    except (TypeError, ValueError):
        timeout = 120.0
    messages = [
        SystemMessage(content="You are a synthesis engine for multi-agent patterns."),
        HumanMessage(content=prompt + "\n\n" + combined),
    ]
    text, _tail, last_chunk = await stream_or_invoke_llm(
        llm,
        messages,
        agent,
        timeout=timeout,
        phase="pattern_synthesis",
    )
    usage = getattr(last_chunk, "usage_metadata", None) or {}
    return ExecutionResult(
        pattern_used=analysis.pattern,
        query=query,
        output=text or combined or "Synthesis produced no output.",
        success=bool(text or combined),
        analysis=analysis,
        token_usage=usage or {},
        metadata={"synthesis": True},
    )
