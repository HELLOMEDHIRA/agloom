"""Swarm pattern — parallel role-based agents with peer deliberation synthesis."""

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
from ._resolve import resolve_worker_configs
from ._steps_accounting import steps_taken_from_audit
from ._synthesis_contract import (
    ALL_PATTERN_WORKERS_FAILED_ERROR,
    PH_AGENT_PERSPECTIVES,
    PH_ORIGINAL_QUERY,
    human_message_body_replace_placeholders,
    pattern_synthesis_success,
)
from .hitl import run_workers_with_hitl

logger = get_logger(__name__)


SWARM_SYNTHESIS_PROMPT = """\
You are synthesizing a multi-agent deliberation where each agent contributed \
a DISTINCT perspective, role, or argument.

Your job is NOT to simply summarize each perspective. Instead:
1. Identify key POINTS OF AGREEMENT across agents
2. Identify key POINTS OF TENSION or disagreement
3. Provide an EMERGENT SYNTHESIS — the insight that arises from the combination \
of perspectives that no single agent could produce alone

ORIGINAL QUERY:
__AGLOOM_ORIGINAL_QUERY__

AGENT PERSPECTIVES:
__AGLOOM_AGENT_PERSPECTIVES__

YOUR SYNTHESIS:
Provide a balanced, insightful synthesis. Be specific — reference the actual \
arguments made by each agent."""


async def handle_swarm(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Build role-based worker plans, run all in parallel with L3/L4 HITL,
    then synthesize via peer deliberation (emergent insights, not summaries).
    """
    agent_name = agent.get("name", "Agent")
    llm = agent["llm"]
    ml = agent.get("max_step_output_length", 0)
    steps: list = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    raw_messages: list = []
    logger.event(f"[Swarm] {agent_name!r} query={query[:60]!r}... agents={len(analysis.subtasks)}")

    if not analysis.subtasks:
        return ExecutionResult(
            query=query,
            pattern_used=PatternType.SWARM,
            output="No swarm agents could be planned for this query.",
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
    for cfg in configs:
        logger.event(
            f"[Swarm] Agent '{cfg.worker_id}' resolved — "
            f"tools={[t.name for t in cfg.tools] if cfg.tools else 'LLM-only'}"
        )

    results, skipped_ids = await run_workers_with_hitl(
        agent=agent,
        configs=configs,
        invoke_config=config,
    )

    if skipped_ids:
        present = {r.worker_id for r in results}
        for cfg in configs:
            if cfg.worker_id in skipped_ids and cfg.worker_id not in present:
                results.append(
                    WorkerResult(
                        worker_id=cfg.worker_id,
                        task=cfg.task,
                        output="Skipped at user request (interrupt_before_workers).",
                        signal=SignalType.HALTED,
                        error="UserSkipped",
                    )
                )

    for wr in results:
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

    for wr in results:
        raw_messages.extend(getattr(wr, "messages", []))

    if skipped_ids:
        logger.event(f"[Swarm] Skipped agents: {skipped_ids}")

    succeeded = [r for r in results if r.signal == SignalType.SUCCESS]
    logger.event(f"[Swarm] {len(succeeded)}/{len(results)} agents succeeded.")

    from ..orchestrator.hooks import maybe_spawn_conflict_resolution

    conflict_resolution = await maybe_spawn_conflict_resolution(
        agent,
        config,
        query,
        [r.output for r in succeeded],
    )
    if conflict_resolution is not None and conflict_resolution.success:
        return ExecutionResult(
            query=query,
            pattern_used=PatternType.SWARM,
            output=conflict_resolution.output,
            steps_taken=steps_taken_from_audit(steps) + conflict_resolution.steps_taken,
            success=True,
            analysis=analysis,
            worker_results=list(results),
            steps=steps + list(conflict_resolution.steps),
            token_usage=_merge_token_usage(usage, conflict_resolution.token_usage),
            messages=raw_messages + list(conflict_resolution.messages),
            metadata={"orchestration_conflict_resolution": PatternType.BLACKBOARD.value},
        )

    if not succeeded:
        if not results and skipped_ids:
            return ExecutionResult(
                query=query,
                pattern_used=PatternType.SWARM,
                output=(
                    "All swarm agents were skipped at user request "
                    f"(interrupt_before_workers): {skipped_ids}"
                ),
                success=True,
                steps_taken=steps_taken_from_audit(steps),
                worker_results=list(results),
                analysis=analysis,
                metadata={"user_skipped_workers": list(skipped_ids)},
                steps=steps,
                token_usage=usage,
                messages=raw_messages,
            )
        logger.error("[Swarm] All agents failed.")
        return ExecutionResult(
            query=query,
            pattern_used=PatternType.SWARM,
            output="All swarm agents failed to produce output.",
            success=False,
            steps_taken=len(results),
            worker_results=list(results),
            error=ALL_PATTERN_WORKERS_FAILED_ERROR,
            analysis=analysis,
            steps=steps,
            token_usage=usage,
            messages=raw_messages,
        )

    perspectives = _format_perspectives(succeeded)
    synthesis_prompt = human_message_body_replace_placeholders(
        SWARM_SYNTHESIS_PROMPT,
        {
            PH_ORIGINAL_QUERY: query,
            PH_AGENT_PERSPECTIVES: perspectives,
        },
    )
    _timeout = agent.get("llm_timeout", 120.0) if isinstance(agent, dict) else 120.0
    t_synth = time.perf_counter()
    synth_input = [
        SystemMessage(
            content=(
                "You are a synthesis engine for a multi-agent deliberation system. "
                "Find emergent insights, not just summaries."
            )
        ),
        HumanMessage(content=synthesis_prompt),
    ]
    synthesis_error: str | None = None
    synth_usage: dict[str, int] = {}
    try:
        synthesis, tail, last_chunk = await stream_or_invoke_llm(
            llm, synth_input, agent, timeout=_timeout, phase="swarm_synthesis"
        )
        raw_messages.extend(tail)
        synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
        synth_usage = _extract_token_usage(last_chunk) if last_chunk else {}
        if synth_usage:
            usage = _merge_token_usage(usage, synth_usage)
    except TimeoutError:
        synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
        synthesis_error = "SynthesisTimeout"
        synthesis = perspectives
    except Exception:
        synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
        synthesis_error = "SynthesisFailed"
        synthesis = perspectives
    steps.append(
        _make_step(
            StepType.LLM_CALL,
            "swarm_synthesis",
            input=query,
            output=synthesis,
            duration_ms=synth_ms,
            max_length=ml,
            usage=synth_usage if synth_usage else {},
            phase="swarm_synthesis",
        )
    )
    logger.event(f"[Swarm] Deliberation synthesis done: {len(synthesis)} chars.")
    logger.event(f"[Swarm] Done: {len(succeeded)} agents, {len(synthesis)} chars.")

    synthesis_degraded = synthesis_error is not None

    return ExecutionResult(
        query=query,
        pattern_used=PatternType.SWARM,
        output=synthesis,
        success=pattern_synthesis_success(worker_results=results, synthesis_degraded=synthesis_degraded),
        steps_taken=steps_taken_from_audit(steps),
        worker_results=list(results),
        error=synthesis_error,
        analysis=analysis,
        metadata={
            "worker_success_count": len(succeeded),
            "worker_total": len(results),
            "synthesis_degraded": synthesis_degraded,
        },
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )


def _format_perspectives(results: list[WorkerResult]) -> str:
    """Format worker outputs as labelled perspective blocks for synthesis."""
    sections = []
    for r in results:
        sections.append(f"[{r.worker_id}]\nRole: {r.task}\n{r.output}")
    return "\n\n".join(sections)
