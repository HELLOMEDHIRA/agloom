"""Per-turn orchestration plan from classifier + agent ceilings."""

from __future__ import annotations

from typing import Any

from agloom.models import QueryAnalysis, PatternType
from agloom.orchestrator.plan import derive_orchestration_from_complexity, resolve_turn_orchestration


def _agent(**kwargs: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "max_pattern_depth": 5,
        "max_orchestration_tokens": 100_000,
        "max_orchestration_llm_calls": 80,
        "enable_auto_escalation": True,
        "orchestration_plan_from_classifier": True,
    }
    base.update(kwargs)
    return base


def test_ceiling_zero_disables_orchestration() -> None:
    plan = resolve_turn_orchestration(_agent(max_pattern_depth=0), QueryAnalysis(
        pattern=PatternType.HYBRID_DAG, complexity=10, reasoning="hard"
    ))
    assert plan.max_depth == 0
    assert plan.source == "disabled"


def test_simple_query_depth_zero() -> None:
    analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=2, reasoning="hi")
    plan = resolve_turn_orchestration(_agent(), analysis)
    assert plan.max_depth == 0
    assert plan.auto_escalation is False


def test_complex_query_clamped_to_ceiling() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.HYBRID_DAG,
        complexity=10,
        reasoning="hard",
        orchestration_depth=10,
        orchestration_token_budget=200_000,
        orchestration_llm_call_budget=200,
        orchestration_auto_escalation=True,
    )
    plan = resolve_turn_orchestration(_agent(max_pattern_depth=3), analysis)
    assert plan.max_depth == 3
    assert plan.max_total_tokens == 100_000
    assert plan.max_total_llm_calls == 80
    assert plan.auto_escalation is True
    assert plan.source == "classifier"


def test_classifier_explicit_depth() -> None:
    analysis = QueryAnalysis(
        pattern=PatternType.REACT,
        complexity=8,
        reasoning="tools",
        orchestration_depth=2,
        orchestration_auto_escalation=False,
    )
    plan = resolve_turn_orchestration(_agent(), analysis)
    assert plan.max_depth == 2
    assert plan.auto_escalation is False


def test_static_mode_uses_agent_ceiling() -> None:
    analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=2, reasoning="hi")
    plan = resolve_turn_orchestration(
        _agent(orchestration_plan_from_classifier=False),
        analysis,
    )
    assert plan.max_depth == 5
    assert plan.source == "agent_static"


def test_derive_from_complexity() -> None:
    low = derive_orchestration_from_complexity(2)
    high = derive_orchestration_from_complexity(9)
    assert low.max_depth == 0
    assert high.max_depth == 4
    assert high.auto_escalation is True
