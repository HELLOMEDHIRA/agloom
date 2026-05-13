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
{query}

AGENT PERSPECTIVES:
{perspectives}

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

    if not succeeded:
        logger.error("[Swarm] All agents failed.")
        return ExecutionResult(
            query=query,
            pattern_used=PatternType.SWARM,
            output="All swarm agents failed to produce output.",
            success=False,
            steps_taken=len(results),
            worker_results=list(results),
            error="AllAgentsFailed",
            analysis=analysis,
            steps=steps,
            token_usage=usage,
            messages=raw_messages,
        )

    perspectives = _format_perspectives(succeeded)
    synthesis_prompt = SWARM_SYNTHESIS_PROMPT.format(
        query=query,
        perspectives=perspectives,
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
    try:
        synthesis, tail, last_chunk = await stream_or_invoke_llm(
            llm, synth_input, agent, timeout=_timeout
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
        )
    )
    logger.event(f"[Swarm] Deliberation synthesis done: {len(synthesis)} chars.")
    logger.event(f"[Swarm] Done: {len(succeeded)} agents, {len(synthesis)} chars.")

    return ExecutionResult(
        query=query,
        pattern_used=PatternType.SWARM,
        output=synthesis,
        success=True,
        steps_taken=len(results) + 1,
        worker_results=list(results),
        error=synthesis_error,
        analysis=analysis,
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )


def _format_perspectives(results: list[WorkerResult]) -> str:
    """Format worker outputs as labelled perspective blocks for synthesis."""
    sections = []
    for r in results:
        sections.append(f"[{r.worker_id.upper()}]\nRole: {r.task}\n{r.output}")
    return "\n\n".join(sections)
