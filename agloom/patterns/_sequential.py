"""Sequential execution engine shared by Pipeline and Planner-Executor patterns."""

from collections import deque

from .. import worker as worker_module
from ..logging_utils import get_logger
from ..models import PatternType, QueryAnalysis, ResolvedWorkerConfig, SignalType, WorkerResult
from ._worker_signals import halted_worker_result, worker_execution_failed
from ..worker import extend_invoke_config_with_event_queue
from ._upstream_context import format_upstream_block, format_upstream_blocks
from .worker_gates import drain_for_halt, get_signal_queue

logger = get_logger(__name__)


def inject_pipeline_input(
    config: ResolvedWorkerConfig,
    prev_result: WorkerResult,
) -> ResolvedWorkerConfig:
    """Inject only the previous step's output (strict A→B→C chain)."""
    block = format_upstream_block(prev_result.worker_id, prev_result.output)
    injected_task = f"{config.task}\n\nINPUT FROM PREVIOUS STEP ({prev_result.worker_id}):\n{block}"
    return config.model_copy(update={"task": injected_task})


def inject_planner_context(
    config: ResolvedWorkerConfig,
    history: list[WorkerResult],
) -> ResolvedWorkerConfig:
    """Inject full execution history so the worker can reason from all prior steps."""
    if not history:
        return config
    history_block = "\n\n".join(
        f"Task: {r.task}\nStatus: {r.signal.value}\n{format_upstream_block(r.worker_id, r.output)}"
        for r in history
    )
    injected_task = f"{config.task}\n\nEXECUTION HISTORY:\n{history_block}"
    return config.model_copy(update={"task": injected_task})


def topological_sort(
    configs: list[ResolvedWorkerConfig],
) -> list[ResolvedWorkerConfig]:
    """Topological order of workers by ``depends_on``; raises on cycles or bad refs."""
    id_map = {c.worker_id: c for c in configs}
    in_degree = {c.worker_id: 0 for c in configs}
    children = {c.worker_id: [] for c in configs}

    for c in configs:
        for dep in c.depends_on:
            if dep not in id_map:
                raise ValueError(f"Worker '{c.worker_id}' depends on unknown worker '{dep}'.")
            children[dep].append(c.worker_id)
            in_degree[c.worker_id] += 1

    queue = deque(c.worker_id for c in configs if in_degree[c.worker_id] == 0)
    result = []

    while queue:
        node = queue.popleft()
        result.append(id_map[node])
        for child in children[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(result) != len(configs):
        resolved = {r.worker_id for r in result}
        cycle_nodes = [c.worker_id for c in configs if c.worker_id not in resolved]
        raise ValueError(f"Circular dependency detected among workers: {cycle_nodes}")

    return result


async def run_sequential_workers(
    agent: dict,
    configs: list[ResolvedWorkerConfig],
    mode: str,
    stop_on_failure: bool = True,
    invoke_config: dict | None = None,
) -> list[WorkerResult]:
    """Run worker configs in topological order (``depends_on``).

    Args:
        agent: Agent dict (``llm``, ``name``, …).
        configs: Worker plans with ``worker_id`` and ``depends_on``.
        mode: ``"pipeline"`` (previous step output only) or ``"planner_executor"`` (full history).
        stop_on_failure: If True, abort the chain after a failed worker (pipeline default).
        invoke_config: Forwarded to ``run_worker`` (e.g. LangGraph ``configurable``).

    ``HALT_ALL`` on the signal queue skips remaining steps (observed **between**
    step iterations only — unlike parallel patterns, there is no shared task
    listener that cancels an in-flight worker mid-step). Returns ordered ``WorkerResult`` list.
    """
    agent_name = agent.get("name", "Agent")
    llm = agent["llm"]
    signal_queue = get_signal_queue(agent, invoke_config)

    sorted_configs = topological_sort(configs)
    results_map: dict[str, WorkerResult] = {}
    ordered_results: list[WorkerResult] = []
    failed_ids: set[str] = set()

    logger.event(f"[Sequential/{mode}] {agent_name} — execution order: {[c.worker_id for c in sorted_configs]}")

    for idx, config in enumerate(sorted_configs):
        if signal_queue:
            halt = await drain_for_halt(
                signal_queue,
                caller_name=f"{agent_name}[{mode}]",
            )
            if halt:
                logger.warning(
                    f"[Sequential/{mode}] {agent_name} — "
                    f"HALT_ALL at step {idx + 1}/{len(sorted_configs)}. "
                    f"Stopping {len(sorted_configs) - idx} remaining step(s)."
                )
                for rem in sorted_configs[idx:]:
                    ordered_results.append(
                        halted_worker_result(
                            worker_id=rem.worker_id,
                            task=rem.task,
                            output="Skipped — HALT_ALL received before this step.",
                        )
                    )
                break

        upstream_failed = [d for d in config.depends_on if d in failed_ids]
        if upstream_failed:
            if stop_on_failure:
                skipped = WorkerResult(
                    worker_id=config.worker_id,
                    task=config.task,
                    output=(f"Skipped — upstream worker '{upstream_failed[0]!r}' failed."),
                    signal=SignalType.FAILED,
                    error="UpstreamFailure",
                )
                results_map[config.worker_id] = skipped
                ordered_results.append(skipped)
                failed_ids.add(config.worker_id)
                for rem in sorted_configs[idx + 1 :]:
                    ordered_results.append(
                        WorkerResult(
                            worker_id=rem.worker_id,
                            task=rem.task,
                            output=(f"Skipped — upstream worker '{config.worker_id!r}' failed."),
                            signal=SignalType.FAILED,
                            error="UpstreamFailure",
                        )
                    )
                logger.warning(
                    f"[Sequential/{mode}] Worker '{config.worker_id}' "
                    f"has failed upstream {upstream_failed} — "
                    f"stopping chain (stop_on_failure=True)."
                )
                break
            logger.warning(
                f"[Sequential/{mode}] Worker '{config.worker_id}' "
                f"has failed upstream {upstream_failed} — "
                f"running anyway (stop_on_failure=False)."
            )

        if mode == "pipeline" and config.depends_on:
            predecessors = [results_map[d] for d in config.depends_on if d in results_map]
            ok_preds = [r for r in predecessors if r.signal == SignalType.SUCCESS]
            if len(ok_preds) == 1:
                config = inject_pipeline_input(config, ok_preds[0])
            elif len(ok_preds) > 1:
                combined = format_upstream_blocks(
                    [(r.worker_id, f"status {r.signal.value}\n{r.output}") for r in ok_preds]
                )
                injected = (
                    f"{config.task}\n\nINPUT FROM PREVIOUS STEPS "
                    f"({', '.join(r.worker_id for r in ok_preds)}):\n{combined}"
                )
                config = config.model_copy(update={"task": injected})
                logger.event(
                    f"[Sequential/pipeline] Merging {len(ok_preds)} predecessor outputs "
                    f"into worker {config.worker_id!r}"
                )

        elif mode == "planner_executor":
            history = [results_map[dep] for dep in config.depends_on if dep in results_map]
            if history:
                config = inject_planner_context(config, history)

        logger.event(
            f"[Sequential/{mode}] {agent_name} — "
            f"step {idx + 1}/{len(sorted_configs)} "
            f"worker='{config.worker_id}' depends_on={config.depends_on}"
        )
        from ..orchestrator.hooks import run_worker_or_dispatch

        step_analysis = (invoke_config or {}).get("_query_analysis")
        if not isinstance(step_analysis, QueryAnalysis):
            step_analysis = QueryAnalysis(
                pattern=PatternType.REACT, complexity=5, reasoning="sequential"
            )
        result = await run_worker_or_dispatch(
            agent, config, llm, invoke_config, step_analysis
        )
        results_map[config.worker_id] = result
        ordered_results.append(result)

        if worker_execution_failed(result.signal):
            failed_ids.add(config.worker_id)
            if stop_on_failure:
                logger.warning(
                    f"[Sequential/{mode}] Worker '{config.worker_id}' failed — stopping chain (stop_on_failure=True)."
                )
                for rem in sorted_configs[idx + 1 :]:
                    ordered_results.append(
                        WorkerResult(
                            worker_id=rem.worker_id,
                            task=rem.task,
                            output=(f"Skipped — upstream worker '{config.worker_id!r}' failed."),
                            signal=SignalType.FAILED,
                            error="UpstreamFailure",
                        )
                    )
                break

    return ordered_results
