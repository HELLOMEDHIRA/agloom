"""Hybrid DAG pattern — mixed parallel + sequential execution across dependency levels."""

import asyncio
import time

from langchain_core.messages import HumanMessage, SystemMessage

from ..llm_streaming import stream_or_invoke_llm
from ..logging_utils import get_logger
from ..models import (
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    SignalType,
    StepType,
    WorkerPlan,
    WorkerResult,
    _extract_token_usage,
    _make_step,
    _merge_token_usage,
)
from ._dag import group_by_level, inject_dag_context
from ._resolve import resolve_worker_configs
from ._steps_accounting import steps_taken_from_audit
from ._synthesis_contract import (
    ALL_PATTERN_WORKERS_FAILED_ERROR,
    PH_ORIGINAL_QUERY,
    PH_WORKER_OUTPUTS,
    human_message_body_replace_placeholders,
    pattern_synthesis_success,
)
from .hitl import run_workers_with_hitl

logger = get_logger(__name__)


HYBRID_DAG_SYNTHESIS_PROMPT = """\
You are the final synthesizer of a multi-stage agent pipeline.
Workers executed in a dependency graph — some in parallel, some sequentially.
Combine all results into a single coherent, well-structured final answer.

ORIGINAL QUERY:
__AGLOOM_ORIGINAL_QUERY__

WORKER OUTPUTS (in execution order):
__AGLOOM_WORKER_OUTPUTS__

FINAL ANSWER:
Provide a complete, unified answer that integrates all worker findings."""


async def handle_hybrid_dag(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Group workers into DAG levels, execute each level in parallel with L3/L4
    HITL, inject dependency outputs between levels, then synthesize.
    A shared halt_event propagates HALT_ALL across levels.
    """
    agent_name = agent.get("name", "Agent")
    llm = agent["llm"]
    ml = agent.get("max_step_output_length", 0)
    steps: list = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    raw_messages: list = []
    logger.event(f"[HYBRID_DAG] {agent_name!r} query={query[:60]!r}... subtasks={len(analysis.subtasks)}")

    if not analysis.subtasks:
        return ExecutionResult(
            query=query,
            pattern_used=PatternType.HYBRID_DAG,
            output="No DAG workers could be planned for this query.",
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

    configs = resolve_worker_configs(agent, plans)

    levels = group_by_level(configs)
    logger.event(
        f"[HYBRID_DAG] {len(configs)} workers → {len(levels)} levels: "
        + ", ".join(f"L{i}:{[c.worker_id for c in lvl]}" for i, lvl in enumerate(levels))
    )

    halt_event: asyncio.Event = asyncio.Event()

    all_results: list[WorkerResult] = []
    completed: dict[str, WorkerResult] = {}
    cumulative_skipped: list[str] = []

    for level_idx, level_configs in enumerate(levels):
        if halt_event.is_set():
            logger.warning(f"[HYBRID_DAG] HALT_ALL propagated — skipping Level {level_idx} and all subsequent levels.")
            for cfg in level_configs:
                wr = WorkerResult(
                    worker_id=cfg.worker_id,
                    task=cfg.task,
                    output=f"Skipped — HALT_ALL fired in Level {level_idx - 1}.",
                    signal=SignalType.HALTED,
                    error="HALT_ALL",
                )
                all_results.append(wr)
                completed[cfg.worker_id] = wr
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
            continue

        logger.event(f"[HYBRID_DAG] Level {level_idx}: {len(level_configs)} workers in parallel")

        enriched = [inject_dag_context(cfg, completed) for cfg in level_configs]
        for cfg in enriched:
            logger.event(
                f"[HYBRID_DAG] Worker '{cfg.worker_id}' — "
                f"tools={[t.name for t in cfg.tools] if cfg.tools else 'LLM-only'} "
                f"deps={cfg.depends_on or []}"
            )

        from ..orchestrator.hooks import run_dag_level_workers

        level_results, skipped = await run_dag_level_workers(
            agent=agent,
            configs=enriched,
            invoke_config=config,
            analysis=analysis,
            halt_event=halt_event,
        )

        if skipped:
            logger.event(f"[HYBRID_DAG] Level {level_idx} skipped workers: {skipped}")
        cumulative_skipped.extend(skipped)

        succeeded = sum(1 for r in level_results if r.signal == SignalType.SUCCESS)
        logger.event(f"[HYBRID_DAG] Level {level_idx} done: {succeeded}/{len(level_results)} workers succeeded.")

        from ..orchestrator.hooks import recover_failed_workers

        level_results = await recover_failed_workers(agent, config, level_results)

        for result in level_results:
            all_results.append(result)
            completed[result.worker_id] = result
            steps.append(
                _make_step(
                    StepType.WORKER_END,
                    result.worker_id,
                    input=result.task,
                    output=result.output,
                    duration_ms=result.elapsed_ms,
                    signal=result.signal.value,
                    max_length=ml,
                )
            )
            if result.token_usage:
                usage = _merge_token_usage(usage, result.token_usage)
            raw_messages.extend(getattr(result, "messages", []))

    total_success = sum(1 for r in all_results if r.signal == SignalType.SUCCESS)
    total = len(all_results)

    if total_success == 0:
        if total == 0 and cumulative_skipped:
            return ExecutionResult(
                query=query,
                pattern_used=PatternType.HYBRID_DAG,
                output=(
                    "All DAG workers were skipped at user request "
                    f"(interrupt_before_workers): {cumulative_skipped}"
                ),
                success=True,
                steps_taken=steps_taken_from_audit(steps),
                worker_results=all_results,
                analysis=analysis,
                metadata={"user_skipped_workers": list(cumulative_skipped)},
                steps=steps,
                token_usage=usage,
                messages=raw_messages,
            )
        halted = [r for r in all_results if r.signal == SignalType.HALTED]
        if halted and total_success == 0:
            logger.event(f"[HYBRID_DAG] Halted by user ({len(halted)} worker(s)).")
            return ExecutionResult(
                query=query,
                pattern_used=PatternType.HYBRID_DAG,
                output="DAG execution halted by user.",
                success=False,
                steps_taken=steps_taken_from_audit(steps),
                worker_results=all_results,
                error="HALT_ALL",
                analysis=analysis,
                steps=steps,
                token_usage=usage,
                messages=raw_messages,
                metadata={"halted_workers": [r.worker_id for r in halted]},
            )
        logger.error("[HYBRID_DAG] All workers failed.")
        return ExecutionResult(
            query=query,
            pattern_used=PatternType.HYBRID_DAG,
            output="All workers in the DAG failed.",
            success=False,
            steps_taken=steps_taken_from_audit(steps),
            worker_results=all_results,
            error=ALL_PATTERN_WORKERS_FAILED_ERROR,
            analysis=analysis,
            steps=steps,
            token_usage=usage,
            messages=raw_messages,
        )

    outputs_block = _format_all_outputs(all_results)
    synthesis_prompt = human_message_body_replace_placeholders(
        HYBRID_DAG_SYNTHESIS_PROMPT,
        {
            PH_ORIGINAL_QUERY: query,
            PH_WORKER_OUTPUTS: outputs_block,
        },
    )
    _timeout = agent.get("llm_timeout", 120.0) if isinstance(agent, dict) else 120.0
    t_synth = time.perf_counter()
    synth_input = [
        SystemMessage(
            content=(
                "You are the final synthesizer of a multi-stage agent pipeline. Produce a complete, unified answer."
            )
        ),
        HumanMessage(content=synthesis_prompt),
    ]
    synthesis_error: str | None = None
    synth_usage: dict[str, int] = {}
    try:
        synthesis, tail, last_chunk = await stream_or_invoke_llm(
            llm, synth_input, agent, timeout=_timeout, phase="hybrid_dag_synthesis"
        )
        raw_messages.extend(tail)
        synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
        synth_usage = _extract_token_usage(last_chunk) if last_chunk else {}
        if synth_usage:
            usage = _merge_token_usage(usage, synth_usage)
    except TimeoutError:
        synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
        synthesis_error = "SynthesisTimeout"
        synthesis = outputs_block
    except Exception:
        synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
        synthesis_error = "SynthesisFailed"
        synthesis = outputs_block
    steps.append(
        _make_step(
            StepType.LLM_CALL,
            "hybrid_dag_synthesis",
            input=query,
            output=synthesis,
            duration_ms=synth_ms,
            max_length=ml,
            usage=synth_usage if synth_usage else {},
            phase="hybrid_dag_synthesis",
        )
    )
    logger.event(f"[HYBRID_DAG] Synthesis done: {len(synthesis)} chars.")
    logger.event(
        f"[HYBRID_DAG] Done: {total_success}/{total} workers succeeded, {len(levels)} levels, {len(synthesis)} chars."
    )

    worker_success = sum(1 for r in all_results if r.signal == SignalType.SUCCESS)
    synthesis_degraded = synthesis_error is not None

    return ExecutionResult(
        query=query,
        pattern_used=PatternType.HYBRID_DAG,
        output=synthesis,
        success=pattern_synthesis_success(worker_results=all_results, synthesis_degraded=synthesis_degraded),
        steps_taken=steps_taken_from_audit(steps),
        worker_results=all_results,
        error=synthesis_error,
        analysis=analysis,
        metadata={
            "worker_success_count": worker_success,
            "worker_total": total,
            "synthesis_degraded": synthesis_degraded,
        },
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )


def _format_all_outputs(results: list[WorkerResult]) -> str:
    """Format all worker results in execution order for synthesis."""
    sections = []
    for r in results:
        status = "OK" if r.signal == SignalType.SUCCESS else "FAIL"
        sections.append(f"{status} [{r.worker_id}] — {r.task}\n{r.output}")
    return "\n\n".join(sections)
