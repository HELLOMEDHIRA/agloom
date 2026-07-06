"""Tool resolution — maps required_tools name strings to actual tool objects."""

from ..src.classifier import query_needs_registered_tools
from ..src.logging_utils import get_logger
from ..src.models import AgentEvent, QueryAnalysis, ResolvedWorkerConfig, SubTask, WorkerPlan

logger = get_logger(__name__)


def _notify_missing_tools(agent: dict, worker_id: str, missing: list[str]) -> None:
    """Log and optionally surface missing ``required_tools`` on the live event queue."""
    names = ", ".join(missing)
    msg = (
        f"Worker '{worker_id}': required tool(s) not in registry ({names}) — "
        "running LLM-only; behaviour may differ from the plan."
    )
    logger.warning(f"[Resolve] {msg}")
    queue = agent.get("_event_queue")
    if queue is None:
        return
    try:
        queue.put_nowait(
            AgentEvent(
                type="thinking",
                data={
                    "step": "tool_resolve",
                    "label": "Tool resolution warning",
                    "detail": msg,
                },
            )
        )
    except Exception:
        logger.debug("[Resolve] could not enqueue missing-tools warning", exc_info=True)


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
    harness_focus = (agent.get("_harness_execution_context") or "").strip()

    for subtask in subtasks:
        resolved_tools = []
        missing_tools: list[str] = []
        task_text = subtask.task
        if harness_focus:
            task_text = f"{harness_focus}\n\n{task_text}"

        if subtask.required_tools:
            for tool_name in subtask.required_tools:
                tool = tool_map.get(tool_name)
                if tool:
                    resolved_tools.append(tool)
                else:
                    missing_tools.append(tool_name)
        elif tool_map and query_needs_registered_tools(task_text or ""):
            resolved_tools = list(tool_map.values())
            logger.event(
                f"[Resolve] Worker '{subtask.worker_id}' inherited all {len(resolved_tools)} "
                f"agent tool(s) (empty required_tools, task needs tools)"
            )

        if missing_tools:
            _notify_missing_tools(agent, subtask.worker_id, missing_tools)

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
        try:
            rl = int(agent.get("react_recursion_limit", 25))
        except (TypeError, ValueError):
            rl = 25
        rl = max(1, min(rl, 500))
        configs.append(
            ResolvedWorkerConfig(
                worker_id=subtask.worker_id,
                task=task_text,
                system_prompt=instr if instr else default_sp,
                tools=resolved_tools,
                depends_on=subtask.depends_on or [],
                context=dict(subtask.context) if subtask.context else {},
                llm_timeout=float(agent.get("llm_timeout", 120.0)),
                recursion_limit=rl,
                max_retries=agent.get("max_retries", 2),
                retry_delay=agent.get("retry_delay", 1.0),
                missing_tools=missing_tools,
            )
        )

    return configs
