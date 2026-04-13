"""Supervisor pattern — manager decomposes, parallel workers execute, manager synthesizes."""

import asyncio
import time

from langchain_core.messages import HumanMessage, SystemMessage

from ..logging_utils import get_logger
from ..models import (
    AgentEvent,
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    StepType,
    WorkerPlan,
    WorkerResult,
    _make_step,
    _merge_token_usage,
)
from ._resolve import resolve_worker_configs
from .hitl import run_workers_with_hitl

logger = get_logger(__name__)


MANAGER_AGGREGATION_PROMPT = """You are a Synthesis Manager. Multiple specialist workers have completed \
their tasks in parallel. Synthesize all their results into a single, clear, comprehensive answer.

Rules:
- Integrate all worker outputs — do not drop any result.
- Resolve conflicts or overlaps with clear reasoning.
- If a worker failed, note it briefly and continue with available results.
- Output must directly answer the original query.
- Be concise but complete."""


MANAGER_PLANNING_PROMPT = """You are a Task Decomposition Manager for a parallel AI agent system. \
Decompose the query into independent subtasks that can run in PARALLEL. Each subtask should be \
self-contained — workers do NOT share state. Return a clear list of subtasks with specific, \
actionable task descriptions."""


async def handle_supervisor(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Build worker plans from subtasks (or fallback manager LLM), resolve tools,
    run workers in parallel with L3/L4 HITL via run_workers_with_hitl,
    then aggregate all results through a synthesis LLM call.
    """
    name = agent.get("name", "UnifiedAgent")
    steps: list = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    logger.event(f"[Supervisor] {name!r} query={query[:60]!r}... subtasks_from_classifier={len(analysis.subtasks)}")

    plans = await get_worker_plans(agent, query, analysis)
    if not plans:
        logger.warning("[Supervisor] No worker plans generated — returning empty.")
        return ExecutionResult(
            pattern_used=PatternType.SUPERVISOR,
            query=query,
            output="No worker plans could be generated for this query.",
            steps_taken=1,
            success=False,
            analysis=analysis,
            steps=steps,
        )
    logger.event(f"[Supervisor] {len(plans)} worker plans: {[p.worker_id for p in plans]}")

    configs = resolve_worker_configs(agent, plans)

    event_queue = agent.get("_event_queue")

    for wc in configs:
        start_step = _make_step(StepType.WORKER_START, wc.worker_id, input=wc.task[:200])
        steps.append(start_step)
        if event_queue is not None:
            await event_queue.put(
                AgentEvent(
                    type="worker_start",
                    data={"name": wc.worker_id, "input": wc.task[:200]},
                )
            )

    worker_results, skipped_ids = await run_workers_with_hitl(
        agent=agent,
        configs=configs,
        invoke_config=config,
    )
    for wr in worker_results:
        end_step = _make_step(
            StepType.WORKER_END,
            wr.worker_id,
            input=wr.task[:200],
            output=wr.output[:200],
            duration_ms=wr.elapsed_ms,
            signal=wr.signal.value,
        )
        steps.append(end_step)
        if event_queue is not None:
            await event_queue.put(
                AgentEvent(
                    type="worker_end",
                    data={
                        "name": wr.worker_id,
                        "input": wr.task[:200],
                        "output": wr.output[:200],
                        "duration_ms": wr.elapsed_ms,
                        "signal": wr.signal.value,
                    },
                )
            )
        if wr.token_usage:
            usage = _merge_token_usage(usage, wr.token_usage)

    if skipped_ids:
        logger.event(f"[Supervisor] Skipped workers: {skipped_ids}")

    if not worker_results and skipped_ids:
        return ExecutionResult(
            pattern_used=PatternType.SUPERVISOR,
            query=query,
            output=f"All workers were aborted by interrupt_before_workers: {skipped_ids}",
            steps_taken=1,
            success=False,
            analysis=analysis,
            steps=steps,
        )

    t_agg = time.perf_counter()
    output = await aggregate_results(
        agent=agent,
        query=query,
        worker_results=worker_results,
        skipped_ids=skipped_ids,
    )
    agg_ms = round((time.perf_counter() - t_agg) * 1000, 1)
    steps.append(
        _make_step(
            StepType.LLM_CALL,
            "supervisor_aggregate",
            input=query[:200],
            output=output[:200],
            duration_ms=agg_ms,
        )
    )
    total_steps = len(worker_results) + 2
    logger.event(f"[Supervisor] Done: {len(worker_results)} workers, {len(output)} chars.")

    return ExecutionResult(
        pattern_used=PatternType.SUPERVISOR,
        query=query,
        output=output,
        steps_taken=total_steps,
        success=True,
        analysis=analysis,
        worker_results=worker_results,
        steps=steps,
        token_usage=usage,
    )


async def get_worker_plans(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
) -> list[WorkerPlan]:
    if analysis.subtasks:
        return [
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
    logger.event("[Supervisor] No subtasks from classifier — calling manager LLM.")
    return await plan_via_manager_llm(agent, query, analysis)


async def plan_via_manager_llm(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
) -> list[WorkerPlan]:
    from pydantic import BaseModel as PydanticBase

    class PlanList(PydanticBase):
        plans: list[WorkerPlan]

    tool_names = [t.name for t in agent["tools"]]
    try:
        from ..llm_utils import robust_structured_call

        result = await robust_structured_call(
            agent["llm"],
            PlanList,
            [
                SystemMessage(content=MANAGER_PLANNING_PROMPT),
                HumanMessage(
                    content=(
                        f"Decompose this query into parallel worker plans.\n"
                        f"Available tools: {tool_names}\n"
                        f"Query: {query}\n"
                        f"Complexity: {analysis.complexity}/10\n"
                        f"Reasoning: {analysis.reasoning}"
                    )
                ),
            ],
            max_retries=agent.get("structured_max_retries", 2),
            timeout=agent.get("llm_timeout", 120.0),
            caller="Supervisor",
        )
        if result is None:
            raise ValueError("Structured planning returned None")
        logger.event(f"[Supervisor] Manager LLM planned {len(result.plans)} workers.")
        return result.plans
    except Exception as e:
        logger.error(f"[Supervisor] Manager LLM planning failed: {e}")
        return [
            WorkerPlan(
                worker_id="worker-1",
                task=query,
                system_instruction="You are a helpful AI assistant.",
                required_tools=[],
            )
        ]


async def aggregate_results(
    agent: dict,
    query: str,
    worker_results: list[WorkerResult],
    skipped_ids: list[str],
) -> str:
    """Synthesize all worker outputs via an LLM call.

    When _event_queue is present, streams tokens in real-time via
    llm.astream() so users see the synthesis being composed live.
    """
    if not worker_results:
        return "No worker results to aggregate."

    results_text = "\n".join(
        f"--- Worker {r.worker_id} | Status: {r.signal.value} ---\nTask: {r.task}\nResult: {r.output}"
        for r in worker_results
    )
    skipped_note = f"\nThe following workers were skipped: {skipped_ids}" if skipped_ids else ""
    messages = [
        SystemMessage(content=MANAGER_AGGREGATION_PROMPT),
        HumanMessage(
            content=(
                f"Original query: {query}\n"
                f"Worker results:\n{results_text}"
                f"{skipped_note}\n"
                f"Synthesize all results into a single comprehensive answer."
            )
        ),
    ]
    event_queue = agent.get("_event_queue")
    _timeout = agent.get("llm_timeout", 120.0)

    try:
        if event_queue is not None:
            chunks: list[str] = []

            async def _stream():
                async for chunk in agent["llm"].astream(messages):
                    content = getattr(chunk, "content", "")
                    if content:
                        content = content if isinstance(content, str) else str(content)
                        chunks.append(content)
                        await event_queue.put(AgentEvent(type="token", data={"content": content}))

            await asyncio.wait_for(_stream(), timeout=_timeout)
            output = "".join(chunks)
        else:
            resp = await asyncio.wait_for(
                agent["llm"].ainvoke(messages),
                timeout=_timeout,
            )
            output = resp.content

        logger.event(f"[Supervisor] Aggregation done: {len(output)} chars.")
        return output
    except Exception as e:
        logger.error(f"[Supervisor] Aggregation LLM failed: {e}")
        return "\n".join(f"{r.worker_id}: {r.output}" for r in worker_results)
