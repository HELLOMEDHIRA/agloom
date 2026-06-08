"""Post-execution evaluation (LLM scoring with minimal structural fallback)."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from ..models import ExecutionResult, OrchestrationContext, PatternType, SpawnInstruction

_ORCH_EVAL_SYSTEM = """
You evaluate one step of a recursive AI orchestration run.
Return JSON scores only (numbers 0.0–1.0, not strings).

confidence: how well the output answers the task (1.0 = fully answers it).
quality_score: overall usefulness and coherence.
has_conflicts: true if worker outputs or reasoning contradict each other.
is_incomplete: true if the answer admits gaps or fails to finish the task.
failure_detected: true if the run failed or is unusable.
suggested_pattern: optional next pattern (REACT, REFLECTION, SWARM, BLACKBOARD, SUPERVISOR, HYBRID_DAG, DIRECT) or null.
escalation_reason: one short phrase if suggesting a pattern, else empty.
reasoning: one sentence explaining the scores.
""".strip()

_CONFLICT_EVAL_SYSTEM = """
You detect whether parallel worker outputs contradict each other on the same task.
Return JSON only: has_conflicts (boolean) and reasoning (one short sentence).
""".strip()


class ExecutionEvaluation(BaseModel):
    confidence: float = 0.5
    quality_score: float = 0.5
    has_conflicts: bool = False
    has_hallucination_risk: bool = False
    is_incomplete: bool = False
    disagreement_detected: bool = False
    failure_detected: bool = False
    evaluation_detail: str = ""
    suggested_pattern: PatternType | None = None
    escalation_reason: str = ""
    evaluation_source: str = "fallback"


class OrchestrationEvalScore(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)
    has_conflicts: bool = False
    is_incomplete: bool = False
    failure_detected: bool = False
    suggested_pattern: str | None = None
    escalation_reason: str = ""
    reasoning: str = ""

    @field_validator("confidence", "quality_score", mode="before")
    @classmethod
    def _coerce_float(cls, v: Any) -> float:
        if isinstance(v, str):
            return float(v)
        return v


class ConflictEvalScore(BaseModel):
    has_conflicts: bool = False
    reasoning: str = ""


def _minimal_fallback_evaluation(
    result: ExecutionResult,
    instruction: SpawnInstruction,
) -> ExecutionEvaluation:
    """Structural fallback when LLM evaluation is disabled or unavailable."""
    failure = not result.success or bool(result.error)
    out = (result.output or "").strip()
    incomplete = result.success and not out
    if failure:
        confidence, quality = 0.2, 0.2
    elif incomplete:
        confidence, quality = 0.35, 0.35
    else:
        confidence, quality = 0.5, 0.5
    detail = (
        f"pattern={instruction.pattern.value}; success={result.success}; "
        f"source=fallback; error={result.error or 'none'}"
    )
    return ExecutionEvaluation(
        confidence=confidence,
        quality_score=quality,
        is_incomplete=incomplete,
        failure_detected=failure,
        evaluation_detail=detail,
        evaluation_source="fallback",
    )


def _resolve_eval_llm(agent: dict[str, Any]) -> Any:
    dedicated = agent.get("orchestration_evaluation_llm")
    if dedicated is not None:
        from ..unified_agent import resolve_model

        return resolve_model(dedicated)
    return agent.get("llm")


def _llm_eval_enabled(agent: dict[str, Any]) -> bool:
    return bool(agent.get("enable_orchestration_llm_eval", True))


def _parse_suggested_pattern(raw: str | None) -> PatternType | None:
    if not raw:
        return None
    key = raw.strip().upper().replace("-", "_")
    try:
        return PatternType(key)
    except ValueError:
        return None


async def _llm_evaluation(
    agent: dict[str, Any],
    result: ExecutionResult,
    instruction: SpawnInstruction,
) -> ExecutionEvaluation | None:
    llm = _resolve_eval_llm(agent)
    if llm is None:
        return None
    out = (result.output or "").strip()
    if not out and result.success:
        return None
    prompt = f"""
Task pattern: {instruction.pattern.value}
Escalation context: {instruction.escalation_reason or 'n/a'}
Task preview: {instruction.task[:400]}
Success: {result.success}
Error: {result.error or 'none'}
Output preview:
{out[:800]}
""".strip()
    from ..llm_utils import robust_structured_call

    timeout = min(float(agent.get("llm_timeout", 120.0)), 45.0)
    score = await robust_structured_call(
        llm,
        OrchestrationEvalScore,
        [
            SystemMessage(content=_ORCH_EVAL_SYSTEM),
            HumanMessage(content=prompt),
        ],
        max_retries=int(agent.get("structured_max_retries", 2)),
        timeout=timeout,
        caller=f"OrchestrationEval[{agent.get('name', 'agent')}]",
    )
    if score is None:
        return None
    suggested = _parse_suggested_pattern(score.suggested_pattern)
    return ExecutionEvaluation(
        confidence=score.confidence,
        quality_score=score.quality_score,
        has_conflicts=score.has_conflicts,
        is_incomplete=score.is_incomplete,
        disagreement_detected=score.has_conflicts,
        failure_detected=score.failure_detected,
        evaluation_detail=score.reasoning,
        suggested_pattern=suggested,
        escalation_reason=score.escalation_reason or "",
        evaluation_source="llm",
    )


async def detect_conflicts_via_llm(
    agent: dict[str, Any],
    query: str,
    outputs: list[str],
    *,
    min_chars: int = 60,
) -> bool:
    """LLM-based conflict detection for parallel worker outputs."""
    texts = [o.strip() for o in outputs if isinstance(o, str) and len(o.strip()) >= min_chars]
    if len(texts) < 2 or not _llm_eval_enabled(agent):
        return False
    llm = _resolve_eval_llm(agent)
    if llm is None:
        return False
    preview = "\n\n---\n".join(f"Worker {i + 1}:\n{t[:500]}" for i, t in enumerate(texts[:6]))
    prompt = f"""
Original task:
{query[:400]}

Parallel worker outputs:
{preview}
""".strip()
    from ..llm_utils import robust_structured_call

    timeout = min(float(agent.get("llm_timeout", 120.0)), 30.0)
    score = await robust_structured_call(
        llm,
        ConflictEvalScore,
        [
            SystemMessage(content=_CONFLICT_EVAL_SYSTEM),
            HumanMessage(content=prompt),
        ],
        max_retries=int(agent.get("structured_max_retries", 2)),
        timeout=timeout,
        caller=f"OrchestrationConflict[{agent.get('name', 'agent')}]",
    )
    return bool(score and score.has_conflicts)


async def evaluate_execution(
    agent: dict,
    result: ExecutionResult,
    instruction: SpawnInstruction,
    ctx: OrchestrationContext,
) -> ExecutionEvaluation:
    """LLM quality evaluation on each dispatch step; minimal fallback if LLM unavailable."""
    evaluation: ExecutionEvaluation
    if _llm_eval_enabled(agent):
        llm_eval = await _llm_evaluation(agent, result, instruction)
        evaluation = llm_eval if llm_eval is not None else _minimal_fallback_evaluation(
            result, instruction
        )
    else:
        evaluation = _minimal_fallback_evaluation(result, instruction)

    ctx.confidence_scores.append(evaluation.confidence)
    ctx.quality_scores.append(evaluation.quality_score)
    if evaluation.failure_detected:
        from ..models import FailureRecord

        ctx.failure_history.append(
            FailureRecord(
                worker_id=instruction.parent_worker_id,
                pattern=instruction.pattern,
                error=result.error or result.output[:200],
                depth=ctx.current_depth,
            )
        )
    return evaluation
