"""Recursive adaptive orchestration runtime."""

from .context import fresh_orchestration_context, orchestration_enabled
from .plan import TurnOrchestrationPlan, derive_orchestration_from_complexity, resolve_turn_orchestration
from .dispatch import SpawnAPI, dispatch_pattern
from .runtime import OrchestrationRuntime
from .evaluation import (
    ExecutionEvaluation,
    detect_conflicts_via_llm,
    evaluate_execution,
)
from .escalation import check_escalation
from .hooks import (
    detect_perspective_conflict,
    get_spawn_api,
    maybe_recover_react_failure,
    maybe_spawn_conflict_resolution,
    pattern_spawns_enabled,
    recover_failed_workers,
    run_dag_level_workers,
    run_dag_node_or_dispatch,
    run_worker_or_dispatch,
)

__all__ = [
    "OrchestrationRuntime",
    "SpawnAPI",
    "dispatch_pattern",
    "TurnOrchestrationPlan",
    "derive_orchestration_from_complexity",
    "fresh_orchestration_context",
    "orchestration_enabled",
    "resolve_turn_orchestration",
    "ExecutionEvaluation",
    "detect_conflicts_via_llm",
    "evaluate_execution",
    "check_escalation",
    "detect_perspective_conflict",
    "get_spawn_api",
    "maybe_recover_react_failure",
    "maybe_spawn_conflict_resolution",
    "pattern_spawns_enabled",
    "recover_failed_workers",
    "run_worker_or_dispatch",
    "run_dag_level_workers",
    "run_dag_node_or_dispatch",
]
