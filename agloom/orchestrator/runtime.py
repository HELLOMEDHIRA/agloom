"""OrchestrationRuntime — thin facade over the recursive dispatch engine."""

from __future__ import annotations

from typing import Any

from ..models import ExecutionResult, OrchestrationContext, PatternType, QueryAnalysis, SpawnInstruction
from .context import fresh_orchestration_context, orchestration_enabled
from .dispatch import SpawnAPI, dispatch_pattern
from .evaluation import ExecutionEvaluation, evaluate_execution
from .escalation import check_escalation


class OrchestrationRuntime:
    """Recursive pattern orchestration entry point for ``run_fresh`` and custom integrations."""

    def __init__(self, agent: dict[str, Any]) -> None:
        self._agent = agent

    @property
    def enabled(self) -> bool:
        return orchestration_enabled(self._agent)

    def fresh_context(
        self,
        root_query: str,
        analysis: QueryAnalysis | None = None,
    ) -> OrchestrationContext:
        return fresh_orchestration_context(self._agent, root_query, analysis)

    def turn_plan(self, analysis: QueryAnalysis | None = None):
        from .plan import resolve_turn_orchestration

        return resolve_turn_orchestration(self._agent, analysis)

    async def run(
        self,
        instruction: SpawnInstruction,
        *,
        parent_ctx: OrchestrationContext | None = None,
        analysis: QueryAnalysis | None = None,
        invoke_config: dict | None = None,
    ) -> ExecutionResult:
        registry = self._agent.get("registry")
        return await dispatch_pattern(
            self._agent,
            instruction,
            parent_ctx=parent_ctx,
            analysis=analysis,
            invoke_config=invoke_config,
            registry=registry,
        )

    def spawn_api(
        self,
        ctx: OrchestrationContext,
        invoke_config: dict | None = None,
    ) -> SpawnAPI:
        registry = self._agent.get("registry") or {}
        return SpawnAPI(self._agent, ctx, dict(invoke_config or {}), registry=registry)

    async def evaluate(
        self,
        result: ExecutionResult,
        instruction: SpawnInstruction,
        ctx: OrchestrationContext,
    ) -> ExecutionEvaluation:
        return await evaluate_execution(self._agent, result, instruction, ctx)

    async def escalation_spawns(
        self,
        result: ExecutionResult,
        evaluation: ExecutionEvaluation,
        instruction: SpawnInstruction,
        ctx: OrchestrationContext,
    ) -> list[SpawnInstruction]:
        return await check_escalation(self._agent, result, evaluation, instruction, ctx)
