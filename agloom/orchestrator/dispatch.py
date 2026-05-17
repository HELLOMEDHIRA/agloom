"""Unified recursive pattern dispatcher and spawn API."""

from __future__ import annotations

import time
import uuid
from typing import Any

from ..classifier import analyze_query
from ..logging_utils import get_logger
from ..models import (
    ExecutionResult,
    OrchestrationBudgetExceeded,
    OrchestrationContext,
    OrchestrationCycleDetected,
    OrchestrationStep,
    PatternType,
    QueryAnalysis,
    SpawnInstruction,
    _merge_token_usage,
)
from ..patterns.react import handle_react
from .context import fresh_orchestration_context
from .plan import resolve_turn_orchestration
from .escalation import check_escalation
from .evaluation import ExecutionEvaluation, evaluate_execution
from .safety import apply_timeout, check_cycle, hash_task, record_spawn
from .trace import record_step

logger = get_logger(__name__)


def _agent_float(agent: dict[str, Any], key: str, default: float) -> float:
    val = agent.get(key, default)
    return float(val) if isinstance(val, (int, float)) else default


def _agent_int(agent: dict[str, Any], key: str, default: int) -> int:
    val = agent.get(key, default)
    return val if isinstance(val, int) else default


def _agent_fallback_pattern(agent: dict[str, Any]) -> PatternType | None:
    val = agent.get("fallback_pattern")
    return val if isinstance(val, PatternType) else None


async def _reclassify_if_needed(
    agent: dict[str, Any],
    instruction: SpawnInstruction,
    ctx: OrchestrationContext,
    analysis: QueryAnalysis | None,
) -> QueryAnalysis:
    if analysis is not None and not instruction.reclassify:
        return analysis
    if not instruction.reclassify:
        return QueryAnalysis(
            pattern=instruction.pattern,
            complexity=5,
            reasoning=instruction.escalation_reason or "orchestration_spawn",
        )
    tools = agent.get("tools", [])
    tool_names = instruction.required_tools or [getattr(t, "name", str(t)) for t in tools]
    return await analyze_query(
        llm=agent["llm"],
        query=instruction.task,
        tools=tools,
        skill_context="",
        classifier_timeout=_agent_float(agent, "classifier_timeout", 60.0),
        structured_max_retries=_agent_int(agent, "structured_max_retries", 2),
        fallback_pattern=_agent_fallback_pattern(agent),
    )


def _resolve_handler(
    registry: dict[PatternType, Any],
    pattern: PatternType,
) -> Any:
    handler = registry.get(pattern)
    if handler is not None:
        return handler
    logger.warning(f"No handler for pattern {pattern.value} — falling back to REACT")
    return handle_react


def _usage_count(usage: dict[str, int], key: str) -> int:
    return usage.get(key, 0) or 0


def _apply_usage_to_context(ctx: OrchestrationContext, usage: dict[str, int]) -> None:
    if not usage:
        return
    ctx.total_tokens_used += _usage_count(usage, "total_tokens")
    if not usage.get("total_tokens"):
        ctx.total_tokens_used += _usage_count(usage, "input_tokens") + _usage_count(
            usage, "output_tokens"
        )
    ctx.total_llm_calls += 1


async def _merge_child_result(
    parent: ExecutionResult,
    child: ExecutionResult,
    spawn_instr: SpawnInstruction,
) -> ExecutionResult:
    label = spawn_instr.pattern.value
    merged_out = parent.output or ""
    if child.output:
        block = f"\n\n---\n[{label}: {spawn_instr.escalation_reason or 'follow-up'}]\n{child.output}"
        merged_out = (merged_out + block).strip() if merged_out else child.output
    meta = dict(parent.metadata)
    meta["orchestration_child"] = label
    orch_trace = meta.get("orchestration_trace")
    if isinstance(orch_trace, list):
        meta["orchestration_trace"] = orch_trace
    return parent.model_copy(
        update={
            "output": merged_out,
            "success": parent.success or child.success,
            "worker_results": list(parent.worker_results) + list(child.worker_results),
            "steps_taken": parent.steps_taken + child.steps_taken,
            "token_usage": _merge_token_usage(parent.token_usage, child.token_usage),
            "steps": list(parent.steps) + list(child.steps),
            "metadata": meta,
        }
    )


class SpawnAPI:
    """Injected as ``config['_spawn_api']`` for pattern handlers."""

    def __init__(
        self,
        agent: dict[str, Any],
        ctx: OrchestrationContext,
        invoke_config: dict[str, Any],
        *,
        registry: dict[PatternType, Any],
    ) -> None:
        self._agent = agent
        self._ctx = ctx
        self._invoke_config = invoke_config
        self._registry = registry

    async def spawn_pattern(
        self,
        pattern: PatternType,
        task: str,
        *,
        system_instruction: str = "",
        required_tools: list[str] | None = None,
        parent_worker_id: str = "",
        reason: str = "",
        context: dict[str, str] | None = None,
        reclassify: bool = False,
    ) -> ExecutionResult:
        instr = SpawnInstruction(
            pattern=pattern,
            task=task,
            system_instruction=system_instruction,
            required_tools=required_tools or [],
            parent_worker_id=parent_worker_id or self._ctx.parent_worker_id or "",
            escalation_reason=reason,
            context=context or {},
            reclassify=reclassify,
        )
        return await dispatch_pattern(
            self._agent,
            instr,
            parent_ctx=self._ctx,
            invoke_config=self._invoke_config,
            registry=self._registry,
        )

    async def reclassify_subtask(self, task: str, tools: list | None = None) -> QueryAnalysis:
        agent = {**self._agent, "tools": tools if tools is not None else self._agent.get("tools", [])}
        return await analyze_query(
            llm=agent["llm"],
            query=task,
            tools=agent["tools"],
            skill_context="",
            classifier_timeout=_agent_float(agent, "classifier_timeout", 60.0),
            structured_max_retries=_agent_int(agent, "structured_max_retries", 2),
            fallback_pattern=_agent_fallback_pattern(agent),
        )

    async def escalate_pattern(self, result: ExecutionResult, reason: str) -> ExecutionResult:
        instr = SpawnInstruction(
            pattern=result.pattern_used,
            task=str(result.query),
            escalation_reason=reason,
        )
        evaluation = await evaluate_execution(self._agent, result, instr, self._ctx)
        escalations = await check_escalation(self._agent, result, evaluation, instr, self._ctx)
        merged = result
        for spawn_instr in escalations:
            child = await dispatch_pattern(
                self._agent,
                spawn_instr,
                parent_ctx=self._ctx,
                invoke_config=self._invoke_config,
                registry=self._registry,
            )
            merged = await _merge_child_result(merged, child, spawn_instr)
        return merged


async def dispatch_pattern(
    agent: dict[str, Any],
    instruction: SpawnInstruction,
    *,
    parent_ctx: OrchestrationContext | None = None,
    analysis: QueryAnalysis | None = None,
    invoke_config: dict | None = None,
    registry: dict[PatternType, Any] | None = None,
) -> ExecutionResult:
    """Execute a pattern (and optional escalations) with recursion safety."""
    root_query = parent_ctx.root_query if parent_ctx else instruction.task
    if parent_ctx is None:
        ctx = fresh_orchestration_context(agent, root_query, analysis).model_copy(
            update={"active_pattern": instruction.pattern}
        )
    else:
        ctx = parent_ctx.child_context(
            active_pattern=instruction.pattern,
            worker_id=instruction.parent_worker_id,
        )

    per_spawn_max = instruction.max_depth
    if per_spawn_max is not None:
        ctx = ctx.model_copy(update={"max_depth": per_spawn_max})

    degraded: str | None = None
    try:
        ctx.check_budget()
    except OrchestrationBudgetExceeded as exc:
        degraded = str(exc)
        return ExecutionResult(
            pattern_used=instruction.pattern,
            query=instruction.task,
            output=f"Orchestration stopped: {degraded}",
            success=False,
            error=degraded,
            metadata={"orchestration_degraded": degraded},
        )

    task_hash = hash_task(instruction.task)
    spawn_id = str(uuid.uuid4())[:12]
    try:
        check_cycle(ctx, instruction.pattern, task_hash)
    except OrchestrationCycleDetected as exc:
        degraded = str(exc)
        return ExecutionResult(
            pattern_used=instruction.pattern,
            query=instruction.task,
            output=f"Orchestration stopped: {degraded}",
            success=False,
            error=degraded,
            metadata={"orchestration_degraded": degraded},
        )

    record_spawn(
        ctx,
        spawn_id=spawn_id,
        pattern=instruction.pattern,
        task_hash=task_hash,
        worker_id=instruction.parent_worker_id,
        reason=instruction.escalation_reason or "dispatch",
    )

    reg = registry or agent.get("registry") or {}
    t0 = time.perf_counter()
    record_step(
        ctx,
        OrchestrationStep(
            depth=ctx.current_depth,
            pattern=instruction.pattern,
            worker_id=instruction.parent_worker_id or "root",
            action="enter",
            input_preview=instruction.task[:200],
            reason=instruction.escalation_reason,
        ),
    )

    try:
        resolved_analysis = await _reclassify_if_needed(agent, instruction, ctx, analysis)
        if reg.get(resolved_analysis.pattern) is None and resolved_analysis.pattern != instruction.pattern:
            resolved_analysis = resolved_analysis.model_copy(update={"pattern": instruction.pattern})

        handler = _resolve_handler(reg, resolved_analysis.pattern)
        exec_config = dict(invoke_config or {})
        exec_config["_orchestration_context"] = ctx
        exec_config["_spawn_api"] = SpawnAPI(agent, ctx, exec_config, registry=reg)
        exec_config["_query_analysis"] = resolved_analysis
        exec_config["llm_timeout"] = apply_timeout(agent, ctx)

        result = await handler(agent, instruction.task, resolved_analysis, exec_config)
        _apply_usage_to_context(ctx, result.token_usage)

        evaluation = await evaluate_execution(agent, result, instruction, ctx)
        escalations: list[SpawnInstruction] = []
        if ctx.auto_escalation:
            escalations = await check_escalation(agent, result, evaluation, instruction, ctx)
            for spawn_instr in escalations:
                record_step(
                    ctx,
                    OrchestrationStep(
                        depth=ctx.current_depth,
                        pattern=instruction.pattern,
                        worker_id=instruction.parent_worker_id or "root",
                        action="escalate",
                        reason=spawn_instr.escalation_reason,
                        input_preview=spawn_instr.task[:200],
                    ),
                )
                try:
                    child = await dispatch_pattern(
                        agent,
                        spawn_instr,
                        parent_ctx=ctx,
                        invoke_config=invoke_config,
                        registry=reg,
                    )
                    result = await _merge_child_result(result, child, spawn_instr)
                    _apply_usage_to_context(ctx, child.token_usage)
                except (OrchestrationBudgetExceeded, OrchestrationCycleDetected) as exc:
                    degraded = str(exc)
                    result = result.model_copy(
                        update={
                            "metadata": {
                                **result.metadata,
                                "orchestration_degraded": degraded,
                            }
                        }
                    )
                    break

        duration_ms = round((time.perf_counter() - t0) * 1000, 1)
        record_step(
            ctx,
            OrchestrationStep(
                depth=ctx.current_depth,
                pattern=instruction.pattern,
                worker_id=instruction.parent_worker_id or "root",
                action="complete",
                output_preview=(result.output or "")[:200],
                reason=instruction.escalation_reason,
                duration_ms=duration_ms,
                token_usage=dict(result.token_usage),
                error=result.error,
            ),
            confidence=evaluation.confidence if evaluation else None,
            quality_score=evaluation.quality_score if evaluation else None,
        )
        meta = dict(result.metadata)
        meta["orchestration_trace"] = [s.model_dump() for s in ctx.orchestration_trace]
        if ctx.current_depth == 0:
            turn_plan = resolve_turn_orchestration(agent, analysis)
            meta["orchestration_turn_plan"] = {
                "max_depth": turn_plan.max_depth,
                "max_total_tokens": turn_plan.max_total_tokens,
                "max_total_llm_calls": turn_plan.max_total_llm_calls,
                "auto_escalation": turn_plan.auto_escalation,
                "source": turn_plan.source,
            }
        if degraded:
            meta["orchestration_degraded"] = degraded
        return result.model_copy(update={"metadata": meta})

    except (OrchestrationBudgetExceeded, OrchestrationCycleDetected) as exc:
        degraded = str(exc)
        return ExecutionResult(
            pattern_used=instruction.pattern,
            query=instruction.task,
            output=f"Orchestration stopped: {degraded}",
            success=False,
            error=degraded,
            metadata={"orchestration_degraded": degraded},
        )
