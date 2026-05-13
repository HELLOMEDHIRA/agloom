"""Tool resolution — maps required_tools name strings to actual tool objects."""

from ..logging_utils import get_logger
from ..models import QueryAnalysis, ResolvedWorkerConfig, SubTask, WorkerPlan

logger = get_logger(__name__)


def resolve_worker_configs(
    agent: dict,
    plans: QueryAnalysis | list[WorkerPlan] | list[SubTask],
) -> list[ResolvedWorkerConfig]:
    """Map plan objects → ResolvedWorkerConfig with actual tool instances."""
    subtasks = (
        plans.subtasks
        if isinstance(plans, QueryAnalysis)
        else plans  # list[WorkerPlan] or list[SubTask] — same duck type
    )

    tool_map = {t.name: t for t in agent["tools"]}
    configs = []

    for subtask in subtasks:
        resolved_tools = []

        if subtask.required_tools:
            for tool_name in subtask.required_tools:
                tool = tool_map.get(tool_name)
                if tool:
                    resolved_tools.append(tool)
                else:
                    logger.warning(f"[Resolve] Tool '{tool_name}' not in registry — skipped.")

        if not resolved_tools and subtask.required_tools:
            logger.event(f"[Resolve] Worker '{subtask.worker_id}' has no matched tools — running as LLM-only.")

        logger.event(
            f"[Resolve] Worker '{subtask.worker_id}' resolved → "
            f"tools={[t.name for t in resolved_tools] if resolved_tools else '[] (LLM-only)'}"
        )

        instr = (subtask.system_instruction or "").strip()
        # ``agent["system_prompt"]`` may be missing, None, or whitespace-only; never pass that through as the worker default.
        raw_sp = agent.get("system_prompt")
        if isinstance(raw_sp, str) and raw_sp.strip():
            default_sp = raw_sp.strip()
        else:
            default_sp = "You are a helpful AI assistant."
        configs.append(
            ResolvedWorkerConfig(
                worker_id=subtask.worker_id,
                task=subtask.task,
                system_prompt=instr if instr else default_sp,
                tools=resolved_tools,
                depends_on=subtask.depends_on or [],
                context=dict(subtask.context) if subtask.context else {},
                llm_timeout=float(agent.get("llm_timeout", 120.0)),
                max_retries=agent.get("max_retries", 2),
                retry_delay=agent.get("retry_delay", 1.0),
            )
        )

    return configs
