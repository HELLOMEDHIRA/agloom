"""OrchestrationContext construction and feature flags."""

from __future__ import annotations

from typing import Any

from ..models import OrchestrationContext, QueryAnalysis
from .plan import TurnOrchestrationPlan, resolve_turn_orchestration


def orchestration_enabled(
    agent: dict[str, Any],
    analysis: QueryAnalysis | None = None,
) -> bool:
    """True when this turn should use recursive dispatch."""
    return resolve_turn_orchestration(agent, analysis).max_depth > 0


def fresh_orchestration_context(
    agent: dict[str, Any],
    root_query: str,
    analysis: QueryAnalysis | None = None,
    *,
    plan: TurnOrchestrationPlan | None = None,
) -> OrchestrationContext:
    """Root context for a new user turn."""
    turn_plan = plan or resolve_turn_orchestration(agent, analysis)
    return OrchestrationContext(
        current_depth=0,
        max_depth=turn_plan.max_depth,
        root_query=root_query,
        agent_config=dict(agent),
        max_total_tokens=turn_plan.max_total_tokens,
        max_total_llm_calls=turn_plan.max_total_llm_calls,
        auto_escalation=turn_plan.auto_escalation,
        turn_plan_source=turn_plan.source,
        event_queue=agent.get("_event_queue"),
    )
