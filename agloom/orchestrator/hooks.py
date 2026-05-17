"""Pattern-level spawn helpers (Phase 2 integrations)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ..models import ExecutionResult, PatternType, QueryAnalysis, SignalType, WorkerResult, _merge_token_usage

if TYPE_CHECKING:
    from .dispatch import SpawnAPI


def get_spawn_api(config: dict | None) -> SpawnAPI | None:
    api = (config or {}).get("_spawn_api")
    return api if api is not None else None


def pattern_spawns_enabled(agent: dict[str, Any], config: dict | None) -> bool:
    if get_spawn_api(config) is None:
        return False
    return bool(agent.get("enable_pattern_spawns", True))


def detect_perspective_conflict(outputs: list[str], *, min_chars: int = 60) -> bool:
    """Deprecated token-overlap heuristic; prefer :func:`detect_conflicts_via_llm`."""
    texts = [o.strip() for o in outputs if isinstance(o, str) and len(o.strip()) >= min_chars]
    if len(texts) < 2:
        return False
    sets = [set(t.lower().split()) for t in texts]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            inter = len(sets[i] & sets[j])
            union = len(sets[i] | sets[j])
            if union > 0 and inter / union < 0.12:
                return True
    return False


def worker_result_from_spawn(
    child: ExecutionResult,
    worker_id: str,
    task: str,
) -> WorkerResult:
    signal = SignalType.SUCCESS if child.success else SignalType.FAILED
    return WorkerResult(
        worker_id=worker_id,
        task=task,
        output=child.output or "",
        signal=signal,
        error=child.error,
        token_usage=dict(child.token_usage),
        steps=list(child.steps),
        messages=list(child.messages),
    )


async def recover_failed_workers(
    agent: dict[str, Any],
    config: dict | None,
    worker_results: list[WorkerResult],
    *,
    recovery_pattern: PatternType = PatternType.REFLECTION,
) -> list[WorkerResult]:
    """Replace failed workers with spawned recovery runs when orchestration is active."""
    if not pattern_spawns_enabled(agent, config):
        return worker_results
    spawn_api = get_spawn_api(config)
    assert spawn_api is not None

    updated: list[WorkerResult] = []
    for wr in worker_results:
        if wr.signal == SignalType.SUCCESS:
            updated.append(wr)
            continue
        try:
            child = await spawn_api.spawn_pattern(
                recovery_pattern,
                wr.task,
                parent_worker_id=wr.worker_id,
                reason="worker_failure_recovery",
            )
        except Exception:
            updated.append(wr)
            continue
        if child.success:
            updated.append(worker_result_from_spawn(child, wr.worker_id, wr.task))
        else:
            updated.append(wr)
    return updated


async def maybe_recover_react_failure(
    agent: dict[str, Any],
    config: dict | None,
    query: str | list[Any],
    analysis: QueryAnalysis,
    result: ExecutionResult,
) -> ExecutionResult:
    """Spawn REFLECTION when REACT exits unsuccessfully."""
    if result.success or not pattern_spawns_enabled(agent, config):
        return result
    spawn_api = get_spawn_api(config)
    assert spawn_api is not None
    task = query if isinstance(query, str) else str(query)
    try:
        child = await spawn_api.spawn_pattern(
            PatternType.REFLECTION,
            task,
            reason="react_failure_recovery",
        )
    except Exception:
        return result
    if not child.success:
        return result
    meta = dict(result.metadata)
    meta["orchestration_react_recovery"] = True
    return child.model_copy(
        update={
            "pattern_used": PatternType.REACT,
            "analysis": analysis,
            "steps": list(result.steps) + list(child.steps),
            "token_usage": _merge_token_usage(result.token_usage, child.token_usage),
            "metadata": meta,
        }
    )


async def maybe_spawn_conflict_resolution(
    agent: dict[str, Any],
    config: dict | None,
    query: str,
    outputs: list[str],
    *,
    target_pattern: PatternType = PatternType.BLACKBOARD,
) -> ExecutionResult | None:
    """Spawn deliberation pattern when worker outputs likely conflict."""
    if not detect_perspective_conflict(outputs) or not pattern_spawns_enabled(agent, config):
        return None
    spawn_api = get_spawn_api(config)
    assert spawn_api is not None
    task = (
        f"Resolve conflicting perspectives for the original goal.\n\n"
        f"ORIGINAL QUERY:\n{query}\n\n"
        f"Conflicting outputs were detected among parallel workers. "
        f"Produce a single reconciled answer."
    )
    try:
        return await spawn_api.spawn_pattern(
            target_pattern,
            task,
            reason="conflict_resolution",
        )
    except Exception:
        return None


async def run_dag_node_or_dispatch(
    agent: dict[str, Any],
    worker_config: Any,
    invoke_config: dict | None,
    analysis: QueryAnalysis,
    *,
    complexity_threshold: int = 7,
) -> WorkerResult:
    """HYBRID_DAG node: reclassify + dispatch only for tool nodes or high complexity."""
    from .. import worker as worker_module
    from ..worker import extend_invoke_config_with_event_queue
    from ..patterns.hitl import run_workers_with_hitl

    spawn_api = get_spawn_api(invoke_config)
    dynamic = bool(agent.get("enable_dynamic_dag_nodes", True))
    has_tools = bool(getattr(worker_config, "tools", None))
    use_dynamic = (
        dynamic
        and pattern_spawns_enabled(agent, invoke_config)
        and spawn_api is not None
        and (has_tools or analysis.complexity >= complexity_threshold)
    )
    if not use_dynamic:
        merged = extend_invoke_config_with_event_queue(
            invoke_config, agent.get("_event_queue"), agent=agent
        )
        results, _skipped = await run_workers_with_hitl(
            agent, [worker_config], invoke_config=merged
        )
        return results[0] if results else WorkerResult(
            worker_id=worker_config.worker_id,
            task=worker_config.task,
            output="No worker result.",
            signal=SignalType.FAILED,
        )

    t0 = time.perf_counter()
    try:
        sub_analysis = await spawn_api.reclassify_subtask(
            worker_config.task,
            tools=getattr(worker_config, "tools", None),
        )
        child = await spawn_api.spawn_pattern(
            sub_analysis.pattern,
            worker_config.task,
            parent_worker_id=worker_config.worker_id,
            reason="dag_dynamic_node",
            required_tools=[t.name for t in worker_config.tools] if worker_config.tools else [],
            reclassify=False,
        )
    except Exception as exc:
        merged = extend_invoke_config_with_event_queue(
            invoke_config, agent.get("_event_queue"), agent=agent
        )
        wr = await worker_module.run_worker(worker_config, agent["llm"], invoke_config=merged)
        wr.error = wr.error or str(exc)
        return wr

    wr = worker_result_from_spawn(child, worker_config.worker_id, worker_config.task)
    wr.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return wr


async def run_dag_level_workers(
    agent: dict[str, Any],
    configs: list[Any],
    invoke_config: dict | None,
    analysis: QueryAnalysis,
    *,
    halt_event: Any = None,
) -> tuple[list[WorkerResult], list[str]]:
    """Run a DAG level — parallel dynamic dispatch or standard HITL batch."""
    import asyncio

    from ..models import SignalType
    from ..patterns.hitl import run_workers_with_hitl

    dynamic = bool(agent.get("enable_dynamic_dag_nodes", True)) and pattern_spawns_enabled(
        agent, invoke_config
    )
    if not dynamic:
        return await run_workers_with_hitl(
            agent, configs, invoke_config=invoke_config, halt_event=halt_event
        )

    if halt_event is not None and halt_event.is_set():
        halted = [
            WorkerResult(
                worker_id=cfg.worker_id,
                task=cfg.task,
                output="Skipped — HALT_ALL.",
                signal=SignalType.HALTED,
                error="HALT_ALL",
            )
            for cfg in configs
        ]
        return halted, []

    results = await asyncio.gather(
        *[run_dag_node_or_dispatch(agent, cfg, invoke_config, analysis) for cfg in configs]
    )
    return list(results), []


async def run_worker_or_dispatch(
    agent: dict[str, Any],
    worker_config: Any,
    llm: Any,
    invoke_config: dict | None,
    analysis: QueryAnalysis,
    *,
    complexity_threshold: int = 7,
) -> WorkerResult:
    """Run a sequential step via ``run_worker`` or dynamic ``dispatch_pattern``."""
    from .. import worker as worker_module
    from ..worker import extend_invoke_config_with_event_queue

    spawn_api = get_spawn_api(invoke_config)
    use_dispatch = (
        pattern_spawns_enabled(agent, invoke_config)
        and (
            analysis.complexity >= complexity_threshold
            or bool(getattr(worker_config, "tools", None))
        )
    )
    if not use_dispatch or spawn_api is None:
        merged = extend_invoke_config_with_event_queue(
            invoke_config, agent.get("_event_queue"), agent=agent
        )
        return await worker_module.run_worker(worker_config, llm, invoke_config=merged)

    t0 = time.perf_counter()
    try:
        sub_analysis = await spawn_api.reclassify_subtask(
            worker_config.task,
            tools=getattr(worker_config, "tools", None),
        )
        pattern = sub_analysis.pattern
        child = await spawn_api.spawn_pattern(
            pattern,
            worker_config.task,
            parent_worker_id=worker_config.worker_id,
            reason="sequential_dynamic_dispatch",
            required_tools=[t.name for t in worker_config.tools] if worker_config.tools else [],
        )
    except Exception as exc:
        merged = extend_invoke_config_with_event_queue(
            invoke_config, agent.get("_event_queue"), agent=agent
        )
        wr = await worker_module.run_worker(worker_config, llm, invoke_config=merged)
        wr.error = wr.error or str(exc)
        return wr

    wr = worker_result_from_spawn(child, worker_config.worker_id, worker_config.task)
    wr.elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    return wr
