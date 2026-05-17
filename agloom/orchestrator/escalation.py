"""Escalation rule engine — maps evaluation signals to spawn instructions."""

from __future__ import annotations

from ..models import ExecutionResult, OrchestrationContext, PatternType, SpawnInstruction
from .evaluation import ExecutionEvaluation


def _ruleset(agent: dict) -> str:
    rules = agent.get("escalation_rules") or ["default"]
    if isinstance(rules, str):
        return rules
    return rules[0] if rules else "default"


async def check_escalation(
    agent: dict,
    result: ExecutionResult,
    evaluation: ExecutionEvaluation,
    instruction: SpawnInstruction,
    ctx: OrchestrationContext,
) -> list[SpawnInstruction]:
    """Return follow-up spawns when auto-escalation is enabled and signals fire."""
    if not agent.get("enable_auto_escalation", False):
        return []
    if ctx.max_depth > 0 and ctx.current_depth + 1 >= ctx.max_depth:
        return []

    ruleset = _ruleset(agent)
    task = instruction.task
    base = dict(
        task=task,
        system_instruction=instruction.system_instruction,
        required_tools=list(instruction.required_tools),
        context=dict(instruction.context),
        parent_worker_id=instruction.parent_worker_id,
    )
    spawns: list[SpawnInstruction] = []

    def add(pattern: PatternType, reason: str) -> None:
        spawns.append(SpawnInstruction(pattern=pattern, escalation_reason=reason, **base))

    if evaluation.has_conflicts or evaluation.disagreement_detected:
        add(PatternType.SWARM, "conflict_deliberation")
        if ruleset == "aggressive" and evaluation.failure_detected:
            add(PatternType.BLACKBOARD, "conflict_plus_failure")
        return spawns[:2]

    if evaluation.confidence < 0.4:
        add(PatternType.REFLECTION, "low_confidence")
        return spawns[:1]

    if evaluation.failure_detected:
        if instruction.pattern == PatternType.REACT:
            add(PatternType.REFLECTION, "react_failure_recovery")
        elif instruction.pattern == PatternType.SUPERVISOR:
            add(PatternType.HYBRID_DAG, "supervisor_structured_retry")
        else:
            add(PatternType.REFLECTION, "execution_failure")
        return spawns[:1]

    if evaluation.is_incomplete:
        add(PatternType.BLACKBOARD, "iterative_completion")
        return spawns[:1]

    if evaluation.quality_score < 0.5:
        add(PatternType.REFLECTION, "quality_improvement")
        return spawns[:1]

    if evaluation.suggested_pattern is not None:
        add(evaluation.suggested_pattern, evaluation.escalation_reason or "evaluator_suggestion")
        return spawns[:1]

    return []
