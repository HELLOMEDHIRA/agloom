"""Sequential execution engine shared by Pipeline and Planner-Executor patterns."""

from collections import deque

from .. import worker as worker_module
from ..logging_utils import get_logger
from ..models import ResolvedWorkerConfig, SignalType, WorkerResult
from ..worker import extend_invoke_config_with_event_queue
from .worker_gates import drain_for_halt, get_signal_queue

logger = get_logger(__name__)


def inject_pipeline_input(
    config: ResolvedWorkerConfig,
    prev_result: WorkerResult,
) -> ResolvedWorkerConfig:
    """Inject only the previous step's output (strict A→B→C chain)."""
    injected_task = f"{config.task}\n\nINPUT FROM PREVIOUS STEP ({prev_result.worker_id}):\n{prev_result.output}"
    return config.model_copy(update={"task": injected_task})


def inject_planner_context(
    config: ResolvedWorkerConfig,
    history: list[WorkerResult],
) -> ResolvedWorkerConfig:
    """Inject full execution history so the worker can reason from all prior steps."""
    if not history:
        return config
    history_block = "\n\n".join(
        f"[{r.worker_id}]  Task: {r.task}\nStatus: {r.signal.value}\nResult: {r.output}" for r in history
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

    ``HALT_ALL`` on the signal queue skips remaining steps. Returns ordered ``WorkerResult`` list.
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
        if idx > 0 and signal_queue:
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
                        WorkerResult(
                            worker_id=rem.worker_id,
                            task=rem.task,
                            output="Skipped — HALT_ALL received before this step.",
                            signal=SignalType.FAILED,
                            error="HALT_ALL",
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
            prev_id = config.depends_on[-1]
            prev_result = results_map.get(prev_id)
            if prev_result and prev_result.signal == SignalType.SUCCESS:
                config = inject_pipeline_input(config, prev_result)

        elif mode == "planner_executor":
            history = [results_map[dep] for dep in config.depends_on if dep in results_map]
            if history:
                config = inject_planner_context(config, history)

        logger.event(
            f"[Sequential/{mode}] {agent_name} — "
            f"step {idx + 1}/{len(sorted_configs)} "
            f"worker='{config.worker_id}' depends_on={config.depends_on}"
        )
        merged = extend_invoke_config_with_event_queue(invoke_config, agent.get("_event_queue"))
        result = await worker_module.run_worker(config, llm, invoke_config=merged)
        results_map[config.worker_id] = result
        ordered_results.append(result)

        if result.signal == SignalType.FAILED:
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
