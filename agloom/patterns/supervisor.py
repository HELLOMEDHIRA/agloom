"""Supervisor pattern — manager decomposes, parallel workers execute, manager synthesizes."""

import asyncio
import time

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel as PydanticBaseModel

from ..logging_utils import get_logger
from ..models import (
    AgentEvent,
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    SignalType,
    StepType,
    WorkerPlan,
    WorkerResult,
    _make_step,
    _merge_token_usage,
    _trunc,
)
from ..llm_streaming import astream_llm_to_event_queue
from ._resolve import resolve_worker_configs
from ._steps_accounting import steps_taken_from_audit
from ._synthesis_contract import ALL_PATTERN_WORKERS_FAILED_ERROR, pattern_synthesis_success
from .hitl import run_workers_with_hitl

logger = get_logger(__name__)


class _ManagerPlanList(PydanticBaseModel):
    """Structured output for manager LLM worker decomposition.

    Defined at **module scope** (not inside ``plan_via_manager_llm``) so Pydantic /
    ``with_structured_output`` reuse the same model class and ``robust_structured_call``'s
    LRU cache keys stay stable — nesting under the coroutine would recreate types per call.
    """

    plans: list[WorkerPlan]


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
    raw_messages: list = []
    ml = agent.get("max_step_output_length", 0)
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
            messages=raw_messages,
        )
    logger.event(f"[Supervisor] {len(plans)} worker plans: {[p.worker_id for p in plans]}")

    configs = resolve_worker_configs(agent, plans)

    event_queue = agent.get("_event_queue")

    for wc in configs:
        start_step = _make_step(StepType.WORKER_START, wc.worker_id, input=wc.task, max_length=ml)
        steps.append(start_step)
        if event_queue is not None:
            await event_queue.put(
                AgentEvent(
                    type="worker_start",
                    data={"name": wc.worker_id, "input": _trunc(wc.task, ml)},
                )
            )

    from ..orchestrator.hooks import pattern_spawns_enabled, run_dag_level_workers

    ibi_workers = agent.get("interrupt_before_workers") or []
    use_dispatch_workers = (
        pattern_spawns_enabled(agent, config)
        and bool(agent.get("enable_supervisor_worker_dispatch", True))
        and not ibi_workers
    )
    if use_dispatch_workers:
        worker_results, skipped_ids = await run_dag_level_workers(
            agent=agent,
            configs=configs,
            invoke_config=config,
            analysis=analysis,
        )
    else:
        worker_results, skipped_ids = await run_workers_with_hitl(
            agent=agent,
            configs=configs,
            invoke_config=config,
        )
    for wr in worker_results:
        for step in getattr(wr, "steps", []):
            if step.type not in (StepType.TOOL_CALL, StepType.TOOL_RESULT):
                continue
            steps.append(step)
            if event_queue is not None and not (
                step.metadata.get("wire_emitted") or step.metadata.get("_wire_emitted")
            ):
                event_type = "tool_call" if step.type == StepType.TOOL_CALL else "tool_result"
                await event_queue.put(
                    AgentEvent(
                        type=event_type,
                        data={
                            "worker_id": wr.worker_id,
                            "name": step.name,
                            "input": step.input,
                            "output": step.output,
                            **step.metadata,
                        },
                    )
                )

        end_step = _make_step(
            StepType.WORKER_END,
            wr.worker_id,
            input=wr.task,
            output=wr.output,
            duration_ms=wr.elapsed_ms,
            signal=wr.signal.value,
            max_length=ml,
        )
        steps.append(end_step)
        if event_queue is not None:
            await event_queue.put(
                AgentEvent(
                    type="worker_end",
                    data={
                        "name": wr.worker_id,
                        "input": _trunc(wr.task, ml),
                        "output": _trunc(wr.output, ml),
                        "duration_ms": wr.elapsed_ms,
                        "signal": wr.signal.value,
                    },
                )
            )
        if wr.token_usage:
            usage = _merge_token_usage(usage, wr.token_usage)

    for wr in worker_results:
        raw_messages.extend(getattr(wr, "messages", []))

    if skipped_ids:
        logger.event(f"[Supervisor] Skipped workers: {skipped_ids}")

    from ..orchestrator.hooks import recover_failed_workers

    worker_results = await recover_failed_workers(agent, config, worker_results)

    if not worker_results and skipped_ids:
        return ExecutionResult(
            pattern_used=PatternType.SUPERVISOR,
            query=query,
            output=(
                "All workers were skipped at user request "
                f"(interrupt_before_workers): {skipped_ids}"
            ),
            steps_taken=1,
            success=True,
            analysis=analysis,
            metadata={"user_skipped_workers": list(skipped_ids)},
            steps=steps,
            messages=raw_messages,
        )

    t_agg = time.perf_counter()
    output, agg_msgs, synthesis_degraded, synthesis_error, agg_usage = await aggregate_results(
        agent=agent,
        query=query,
        worker_results=worker_results,
        skipped_ids=skipped_ids,
    )
    raw_messages.extend(agg_msgs)
    agg_ms = round((time.perf_counter() - t_agg) * 1000, 1)
    if agg_usage:
        usage = _merge_token_usage(usage, agg_usage)
    from ..wire_tokens import llm_label_from_run_config

    steps.append(
        _make_step(
            StepType.LLM_CALL,
            "supervisor_aggregate",
            input=query,
            output=output,
            duration_ms=agg_ms,
            max_length=ml,
            usage=agg_usage if agg_usage else {},
            phase="supervisor_aggregate",
            model=llm_label_from_run_config(agent),
        )
    )
    any_success = any(wr.signal == SignalType.SUCCESS for wr in worker_results)
    success = pattern_synthesis_success(worker_results=worker_results, synthesis_degraded=synthesis_degraded)
    err: str | None
    if not any_success:
        err = ALL_PATTERN_WORKERS_FAILED_ERROR
    else:
        err = synthesis_error
    logger.event(f"[Supervisor] Done: {len(worker_results)} workers, {len(output)} chars.")

    return ExecutionResult(
        pattern_used=PatternType.SUPERVISOR,
        query=query,
        output=output,
        steps_taken=steps_taken_from_audit(steps),
        success=success,
        error=err,
        analysis=analysis,
        worker_results=worker_results,
        metadata={
            "synthesis_degraded": synthesis_degraded,
            "worker_success_count": sum(1 for wr in worker_results if wr.signal == SignalType.SUCCESS),
            "worker_total": len(worker_results),
        },
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
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
    tool_names = [t.name for t in agent["tools"]]
    try:
        from ..llm_utils import robust_structured_call

        result = await robust_structured_call(
            agent["llm"],
            _ManagerPlanList,
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
) -> tuple[str, list, bool, str | None, dict[str, int]]:
    """Synthesize all worker outputs via an LLM call.

    When _event_queue is present, streams tokens in real-time via
    llm.astream() so users see the synthesis being composed live.

    Returns ``(output, llm_message_tail, synthesis_degraded, synthesis_error, aggregate_usage)``.
    """
    if not worker_results:
        return "No worker results to aggregate.", [], False, None, {}

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
    llm_messages = list(messages)
    event_queue = agent.get("_event_queue")
    _timeout = agent.get("llm_timeout", 120.0)
    agg_cfg = agent.get("supervisor_aggregate_timeout")
    if agg_cfg is not None:
        try:
            agg_timeout = float(agg_cfg)
        except (TypeError, ValueError):
            agg_timeout = max(30.0, float(_timeout) * 0.5)
    else:
        agg_timeout = max(30.0, float(_timeout) * 0.5)

    try:
        if event_queue is not None:
            output, last_chunk, stream_usage = await astream_llm_to_event_queue(
                agent["llm"], messages, event_queue, timeout=agg_timeout
            )
            from ..wire_tokens import emit_usage_from_llm_response, llm_label_from_run_config

            agg_usage = await emit_usage_from_llm_response(
                agent,
                last_chunk,
                phase="supervisor_aggregate",
                model=llm_label_from_run_config(agent),
                stream_accumulated=stream_usage,
            )
            if last_chunk is not None:
                llm_messages.append(last_chunk)
        else:
            resp = await asyncio.wait_for(
                agent["llm"].ainvoke(messages),
                timeout=agg_timeout,
            )
            from ..wire_tokens import emit_usage_from_llm_response, llm_label_from_run_config

            agg_usage = await emit_usage_from_llm_response(
                agent,
                resp,
                phase="supervisor_aggregate",
                model=llm_label_from_run_config(agent),
            )
            output = resp.content if isinstance(resp.content, str) else str(resp.content)
            llm_messages.append(resp)

        logger.event(f"[Supervisor] Aggregation done: {len(output)} chars.")
        u = agg_usage if isinstance(agg_usage, dict) else {}
        return output, llm_messages, False, None, u
    except TimeoutError:
        logger.error(f"[Supervisor] Aggregation timed out after {agg_timeout}s — falling back to concatenation.")
        output = "\n".join(f"{r.worker_id}: {r.output}" for r in worker_results)
        if event_queue is not None:
            await event_queue.put(AgentEvent(type="aggregation_fallback", data={"reason": "timeout"}))
        return output, llm_messages, True, "SynthesisTimeout", {}
    except Exception as e:
        logger.error(f"[Supervisor] Aggregation LLM failed: {e}")
        output = "\n".join(f"{r.worker_id}: {r.output}" for r in worker_results)
        if event_queue is not None:
            await event_queue.put(AgentEvent(type="aggregation_fallback", data={"reason": "error", "error": str(e)}))
        return output, llm_messages, True, "SynthesisFailed", {}
