"""Planner-executor pattern — sequential reasoning chain where each step sees full prior history."""

import asyncio
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..llm_streaming import stream_or_invoke_llm
from ..logging_utils import get_logger
from ..models import (
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    SignalType,
    StepType,
    WorkerPlan,
    _extract_token_usage,
    _make_step,
    _merge_token_usage,
)
from ..wire_tokens import llm_label_from_run_config
from ._resolve import resolve_worker_configs
from ._sequential import run_sequential_workers
from ._steps_accounting import steps_taken_from_audit
from ._synthesis_contract import ALL_PATTERN_WORKERS_FAILED_ERROR, pattern_synthesis_success

logger = get_logger(__name__)

PLANNER_EXECUTOR_WORKER_PROMPT = """\
You are an execution specialist in a multi-step reasoning chain.
You will receive the full execution history of all previous steps.
Your job: reason from that history to accomplish your specific task.
Build on prior findings — do not repeat work already done.
Be specific and actionable.\
"""

SYNTHESIS_PROMPT = """\
You are a Synthesis Manager in a multi-step reasoning chain.
All execution steps have been completed. Synthesize all results
into a single, coherent, comprehensive final answer.

Rules:
  - Integrate insights from ALL steps — do not drop any finding.
  - Present conclusions clearly — the user only sees this final answer.
  - If a step failed, acknowledge it briefly and reason from what succeeded.
  - Be concise but complete.\
"""


async def handle_planner_executor(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Resolve tools, run workers sequentially with full history context
    (continues on failure), then synthesize all results via manager LLM.
    """
    name = agent.get("name", "UnifiedAgent")
    ml = agent.get("max_step_output_length", 0)
    steps: list = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    raw_messages: list = []
    logger.event(f"[PLANNER_EXECUTOR] ▶ {name} | query={query[:60]}... | steps={len(analysis.subtasks)}")

    if not analysis.subtasks:
        return ExecutionResult(
            pattern_used=PatternType.PLANNER_EXECUTOR,
            query=query,
            output="No execution steps could be planned for this query.",
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
            system_instruction=(
                st.system_instruction
                if (st.system_instruction is not None and st.system_instruction.strip())
                else PLANNER_EXECUTOR_WORKER_PROMPT
            ),
            required_tools=st.required_tools,
            depends_on=st.depends_on,
            context=st.context,
        )
        for st in analysis.subtasks
    ]

    worker_configs = resolve_worker_configs(agent, plans)

    worker_results = await run_sequential_workers(
        agent=agent,
        configs=worker_configs,
        mode="planner_executor",
        stop_on_failure=False,
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

    t_synth = time.perf_counter()
    output, synth_msgs, synthesis_degraded, synth_usage = await _synthesize(agent, query, worker_results)
    raw_messages.extend(synth_msgs)
    synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
    if synth_usage:
        usage = _merge_token_usage(usage, synth_usage)
    steps.append(
        _make_step(
            StepType.LLM_CALL,
            "planner_synthesize",
            input=query,
            output=output,
            duration_ms=synth_ms,
            max_length=ml,
            usage=synth_usage if synth_usage else {},
            phase="planner_synthesize",
            model=llm_label_from_run_config(agent),
        )
    )

    successful = sum(1 for r in worker_results if r.signal == SignalType.SUCCESS)
    all_failed = successful == 0
    logger.event(
        f"[PLANNER_EXECUTOR] ✅ Done — {successful}/{len(worker_results)} steps succeeded, {len(output)} chars."
    )

    err: str | None = None
    if all_failed:
        err = ALL_PATTERN_WORKERS_FAILED_ERROR
    elif synthesis_degraded:
        err = "SynthesisFailed"

    return ExecutionResult(
        pattern_used=PatternType.PLANNER_EXECUTOR,
        query=query,
        output=output,
        steps_taken=steps_taken_from_audit(steps),
        success=pattern_synthesis_success(worker_results=worker_results, synthesis_degraded=synthesis_degraded),
        error=err,
        analysis=analysis,
        worker_results=worker_results,
        metadata={"synthesis_degraded": synthesis_degraded},
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )


async def _synthesize(
    agent: dict,
    query: str,
    worker_results: list,
) -> tuple[str, list, bool, dict[str, int]]:
    """Manager LLM synthesizes all execution steps into a final answer.

    Returns ``(text, llm_messages, synthesis_degraded, synth_usage)``.
    """
    steps_text = "\n\n".join(
        [
            f"Step {i + 1} — {r.worker_id} | Status: {r.signal.value}\nTask  : {r.task}\nResult: {r.output}"
            for i, r in enumerate(worker_results)
        ]
    )

    synth_input = [
        SystemMessage(content=SYNTHESIS_PROMPT),
        HumanMessage(
            content=(
                f"Original query: {query}\n\n"
                f"Execution steps:\n{steps_text}\n\n"
                f"Synthesize all results into a comprehensive final answer:"
            )
        ),
    ]
    llm_messages = list(synth_input)

    try:
        _timeout = agent.get("llm_timeout", 120.0)
        text, llm_messages, last_chunk = await stream_or_invoke_llm(
            agent["llm"], synth_input, agent, timeout=_timeout, phase="planner_synthesize"
        )
        logger.event(f"[PLANNER_EXECUTOR] Synthesis done — {len(text)} chars.")
        synth_usage = _extract_token_usage(last_chunk) if last_chunk else {}
        return text, llm_messages, False, synth_usage
    except Exception as e:
        logger.error(f"[PLANNER_EXECUTOR] Synthesis failed: {e}")
        successful_workers = [r for r in worker_results if r.signal == SignalType.SUCCESS]
        audit_tail = AIMessage(
            content=(
                f"Synthesis LLM failed ({type(e).__name__}: {e}). "
                f"Falling back to the best successful worker output for the user-facing answer; "
                f"full step text is included below for auditing.\n\n{steps_text[:12000]}"
            )
        )
        llm_messages = [*llm_messages, audit_tail]
        if not successful_workers:
            return ("All execution steps failed.", llm_messages, True, {})
        best = max(successful_workers, key=lambda r: len(r.output or ""))
        return (best.output, llm_messages, True, {})
