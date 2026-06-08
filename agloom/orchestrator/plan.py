"""Per-turn orchestration limits from classifier output, clamped to agent ceilings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import QueryAnalysis


@dataclass(frozen=True)
class TurnOrchestrationPlan:
    """Effective orchestration limits for one user turn."""

    max_depth: int
    max_total_tokens: int
    max_total_llm_calls: int
    auto_escalation: bool
    source: str = "derived"


def _clamp_int(value: int, ceiling: int) -> int:
    if ceiling <= 0:
        return max(0, value)
    return max(0, min(value, ceiling))


def _parse_optional_int(raw: int | None) -> int | None:
    if raw is None:
        return None
    return max(0, raw)


def derive_orchestration_from_complexity(complexity: int) -> TurnOrchestrationPlan:
    """Heuristic defaults when the classifier omits orchestration fields."""
    if complexity <= 2:
        return TurnOrchestrationPlan(0, 0, 0, False, source="derived")
    if complexity <= 4:
        return TurnOrchestrationPlan(1, 8_000, 15, False, source="derived")
    if complexity <= 6:
        return TurnOrchestrationPlan(2, 20_000, 30, False, source="derived")
    if complexity <= 8:
        return TurnOrchestrationPlan(3, 50_000, 50, True, source="derived")
    return TurnOrchestrationPlan(4, 100_000, 80, True, source="derived")


def resolve_turn_orchestration(
    agent: dict[str, Any],
    analysis: QueryAnalysis | None = None,
) -> TurnOrchestrationPlan:
    """
    Resolve per-turn orchestration limits.

    ``max_pattern_depth`` on the agent is a **ceiling** (0 = orchestration off).
    When ``orchestration_plan_from_classifier`` is True and *analysis* is present,
    the classifier's suggestions are clamped to those ceilings.
    When False, the agent ceilings are used directly (legacy static mode).
    """
    ceiling_depth = int(agent.get("max_pattern_depth", 0) or 0)
    ceiling_tokens = int(agent.get("max_orchestration_tokens", 0) or 0)
    ceiling_calls = int(agent.get("max_orchestration_llm_calls", 100) or 100)
    agent_allows_escalation = bool(agent.get("enable_auto_escalation", False))

    if ceiling_depth <= 0:
        return TurnOrchestrationPlan(0, 0, 0, False, source="disabled")

    use_classifier = bool(agent.get("orchestration_plan_from_classifier", True))

    if not use_classifier or analysis is None:
        return TurnOrchestrationPlan(
            max_depth=ceiling_depth,
            max_total_tokens=ceiling_tokens,
            max_total_llm_calls=ceiling_calls,
            auto_escalation=agent_allows_escalation,
            source="agent_static",
        )

    derived = derive_orchestration_from_complexity(analysis.complexity)

    depth_raw = _parse_optional_int(analysis.orchestration_depth)
    if depth_raw is None:
        depth = _clamp_int(derived.max_depth, ceiling_depth)
        source = derived.source
    else:
        depth = _clamp_int(depth_raw, ceiling_depth)
        source = "classifier"

    tokens_raw = _parse_optional_int(analysis.orchestration_token_budget)
    if tokens_raw is None:
        tokens = _clamp_int(derived.max_total_tokens, ceiling_tokens)
    else:
        tokens = _clamp_int(tokens_raw, ceiling_tokens)

    calls_raw = _parse_optional_int(analysis.orchestration_llm_call_budget)
    if calls_raw is None:
        calls = _clamp_int(derived.max_total_llm_calls, ceiling_calls)
    else:
        calls = _clamp_int(calls_raw, ceiling_calls)

    if analysis.orchestration_auto_escalation is None:
        turn_escalation = derived.auto_escalation
    else:
        turn_escalation = analysis.orchestration_auto_escalation

    auto_escalation = agent_allows_escalation and turn_escalation and depth > 0

    return TurnOrchestrationPlan(
        max_depth=depth,
        max_total_tokens=tokens,
        max_total_llm_calls=calls,
        auto_escalation=auto_escalation,
        source=source,
    )
