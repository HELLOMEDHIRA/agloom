"""Group ``ResolvedWorkerConfig`` into parallel levels for HYBRID_DAG (same level parallel, levels sequential)."""

from ..logging_utils import get_logger
from ..models import ResolvedWorkerConfig, SignalType, WorkerResult

logger = get_logger(__name__)


def group_by_level(
    configs: list[ResolvedWorkerConfig],
) -> list[list[ResolvedWorkerConfig]]:
    """
    Group workers into parallel execution levels from a DAG.

    Algorithm — iterative level assignment:
      1. Workers with no deps              → Level 0
      2. Workers whose ALL deps are placed → Level = max(dep levels) + 1
      3. Repeat until all placed or circular dep detected

    Returns list of levels: [[level_0_workers], [level_1_workers], ...]
    Raises ValueError on unknown deps or circular dependencies.
    """
    if not configs:
        return []

    config_map = {c.worker_id: c for c in configs}

    # Validate all depends_on references exist
    for c in configs:
        for dep in c.depends_on:
            if dep not in config_map:
                raise ValueError(f"Worker '{c.worker_id}' depends on unknown worker '{dep}'")

    level_map: dict[str, int] = {}
    remaining = list(configs)

    for _ in range(len(configs) + 1):  # +1 guards against circular deps
        if not remaining:
            break

        made_progress = False
        still_remaining = []

        for c in remaining:
            if not c.depends_on:
                level_map[c.worker_id] = 0
                made_progress = True
            elif all(dep in level_map for dep in c.depends_on):
                level_map[c.worker_id] = max(level_map[dep] for dep in c.depends_on) + 1
                made_progress = True
            else:
                still_remaining.append(c)

        remaining = still_remaining

        if not made_progress and remaining:
            cycle_ids = [c.worker_id for c in remaining]
            raise ValueError(f"Circular dependency detected among workers: {cycle_ids}")

    # Bucket configs into their levels
    max_level = max(level_map.values())
    levels: list[list[ResolvedWorkerConfig]] = [[] for _ in range(max_level + 1)]
    for c in configs:
        levels[level_map[c.worker_id]].append(c)

    logger.debug(
        f"[DAG] {len(configs)} workers → "
        f"{len(levels)} levels: "
        + ", ".join(f"L{i}=[{', '.join(c.worker_id for c in lvl)}]" for i, lvl in enumerate(levels))
    )
    return levels


def inject_dag_context(
    config: ResolvedWorkerConfig,
    completed: dict[str, WorkerResult],
) -> ResolvedWorkerConfig:
    """
    Inject outputs from direct dependencies into worker task.

    Design choice vs other patterns:
      PIPELINE        → injects only PREVIOUS step output (A→B→C, strict chain)
      PLANNER_EXECUTOR → injects FULL history of all prior steps
      HYBRID_DAG      → injects only DIRECT dependency outputs (precise DAG edges)

    A worker_5(depends_on=[worker_1, worker_3]) gets ONLY worker_1 and
    worker_3 outputs — not worker_2 or worker_4.
    """
    if not config.depends_on:
        return config

    dep_sections = []
    for dep_id in config.depends_on:
        dep_result = completed.get(dep_id)
        if dep_result and dep_result.signal == SignalType.SUCCESS:
            dep_sections.append(f"━━━ OUTPUT FROM {dep_id} ━━━\n{dep_result.output}")
        elif dep_result and dep_result.signal == SignalType.FAILED:
            dep_sections.append(
                f"━━━ OUTPUT FROM {dep_id} (FAILED) ━━━\n"
                f"This dependency failed: {dep_result.error or 'Unknown error'}. "
                f"Proceed with available information."
            )

    if not dep_sections:
        return config

    enriched_task = config.task + "\n\n" + "\n\n".join(dep_sections)
    return config.model_copy(update={"task": enriched_task})
