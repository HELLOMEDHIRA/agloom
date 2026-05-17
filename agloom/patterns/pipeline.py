"""Pipeline pattern — strictly sequential transformation chain (A→B→C), stops on first failure."""

from ..logging_utils import get_logger
from ..models import (
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    SignalType,
    StepType,
    WorkerPlan,
    _make_step,
    _merge_token_usage,
)
from ._resolve import resolve_worker_configs
from ._sequential import run_sequential_workers
from ._steps_accounting import steps_taken_from_audit

logger = get_logger(__name__)

PIPELINE_SYSTEM_PROMPT = """\
You are a transformation specialist in a data processing pipeline.
Your job: receive the input from the previous step and transform it
according to your specific task.
Output ONLY the transformed result — no meta-commentary, no explanations.
Your output is passed directly as input to the next step.\
"""

PIPELINE_FIRST_WORKER_PROMPT = """\
You are the first step in a data processing pipeline.
Your job: process the initial input and produce output for the next step.
Output ONLY the processed result — no meta-commentary.\
"""

_GENERIC_WORKER_PROMPTS = frozenset(
    {
        "You are a helpful AI assistant.",
    }
)


async def handle_pipeline(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Resolve tools, inject pipeline-aware system prompts, run workers
    sequentially (each receives previous output), return last output.
    """
    name = agent.get("name", "UnifiedAgent")
    ml = agent.get("max_step_output_length", 0)
    steps: list = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    raw_messages: list = []
    logger.event(f"[Pipeline] ▶ {name} | query={query[:60]}... | steps={len(analysis.subtasks)}")

    if not analysis.subtasks:
        return ExecutionResult(
            pattern_used=PatternType.PIPELINE,
            query=query,
            output="No pipeline steps could be planned for this query.",
            steps_taken=1,
            success=False,
            analysis=analysis,
            steps=steps,
            messages=raw_messages,
        )

    plans = [
        WorkerPlan(
            worker_id=st.worker_id,
            task=st.task,
            system_instruction=st.system_instruction,
            required_tools=st.required_tools,
            depends_on=st.depends_on,
            context=st.context,
        )
        for st in analysis.subtasks
    ]

    worker_configs = resolve_worker_configs(agent, plans)

    enhanced_configs = []
    _asp = agent.get("system_prompt")
    agent_default_sp = _asp.strip() if isinstance(_asp, str) else ""
    _generic = _GENERIC_WORKER_PROMPTS | ({agent_default_sp} if agent_default_sp else set())

    for i, wcfg in enumerate(worker_configs):
        prompt = (wcfg.system_prompt or "").strip()
        if not prompt or prompt in _generic:
            prompt = PIPELINE_FIRST_WORKER_PROMPT if i == 0 else PIPELINE_SYSTEM_PROMPT
        enhanced_configs.append(wcfg.model_copy(update={"system_prompt": prompt}, deep=True))

    worker_results = await run_sequential_workers(
        agent=agent,
        configs=enhanced_configs,
        mode="pipeline",
        stop_on_failure=True,
        invoke_config=config,
    )

    for wr in worker_results:
        steps.append(
            _make_step(
                StepType.WORKER_END,
                wr.worker_id,
                input=wr.task,
                output=wr.output,
                duration_ms=wr.elapsed_ms,
                signal=wr.signal.value,
                max_length=ml,
            )
        )
        if wr.token_usage:
            usage = _merge_token_usage(usage, wr.token_usage)

    for wr in worker_results:
        raw_messages.extend(getattr(wr, "messages", []))

    successful = [r for r in worker_results if r.signal is SignalType.SUCCESS]
    if successful:
        final_output = successful[-1].output
        success = True
    else:
        errors = [f"{r.worker_id}: {r.error or 'unknown'}" for r in worker_results if r.error]
        final_output = (
            "Pipeline failed — no successful steps completed.\nErrors:\n  - " + "\n  - ".join(errors)
            if errors
            else "All steps failed without error details."
        )
        success = False

    logger.event(
        f"[Pipeline] ✅ Done — {len(successful)}/{len(worker_results)} steps succeeded, {len(final_output)} chars."
    )

    return ExecutionResult(
        pattern_used=PatternType.PIPELINE,
        query=query,
        output=final_output,
        steps_taken=steps_taken_from_audit(steps),
        success=success,
        analysis=analysis,
        worker_results=worker_results,
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )
