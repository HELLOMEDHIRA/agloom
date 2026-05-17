"""Orchestration trace recording and AGP events."""

from __future__ import annotations

from typing import Any

from ..models import AgentEvent, OrchestrationContext, OrchestrationStep, PatternType


def record_step(
    ctx: OrchestrationContext,
    step: OrchestrationStep,
    *,
    confidence: float | None = None,
    quality_score: float | None = None,
) -> None:
    if confidence is not None or quality_score is not None:
        step = step.model_copy(
            update={
                k: v
                for k, v in (("confidence", confidence), ("quality_score", quality_score))
                if v is not None
            }
        )
    ctx.orchestration_trace.append(step)
    queue = ctx.event_queue
    if queue is None:
        return
    import asyncio

    payload: dict[str, Any] = {
        "depth": step.depth,
        "pattern": step.pattern.value,
        "action": step.action,
        "worker_id": step.worker_id,
        "reason": step.reason,
        "input_preview": step.input_preview,
        "output_preview": step.output_preview,
        "duration_ms": step.duration_ms,
        "error": step.error,
    }
    if confidence is not None:
        payload["confidence"] = confidence
    if quality_score is not None:
        payload["quality_score"] = quality_score
    coro = queue.put(AgentEvent(type="orchestration", data=payload))
    if asyncio.iscoroutine(coro):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            pass


def trace_pattern_label(pattern: PatternType | None) -> str:
    return pattern.value if pattern is not None else "unknown"
