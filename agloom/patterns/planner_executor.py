"""Planner-executor pattern — sequential reasoning chain where each step sees full prior history."""

import asyncio
import time

from langchain_core.messages import HumanMessage, SystemMessage

from ..logging_utils import get_logger
from ..models import ExecutionResult, PatternType, QueryAnalysis, StepType, WorkerPlan, _make_step, _merge_token_usage
from ._resolve import resolve_worker_configs
from ._sequential import run_sequential_workers

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
    steps: list = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
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
        )

    plans = [
        WorkerPlan(
            worker_id=st.worker_id,
            task=st.task,
            system_instruction=st.system_instruction or PLANNER_EXECUTOR_WORKER_PROMPT,
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
                input=wr.task[:200],
                output=wr.output[:200],
                duration_ms=wr.elapsed_ms,
                signal=wr.signal.value,
            )
        )
        if wr.token_usage:
            usage = _merge_token_usage(usage, wr.token_usage)

    t_synth = time.perf_counter()
    output = await _synthesize(agent, query, worker_results)
    synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
    steps.append(
        _make_step(
            StepType.LLM_CALL,
            "planner_synthesize",
            input=query[:200],
            output=output[:200],
            duration_ms=synth_ms,
        )
    )

    successful = sum(1 for r in worker_results if r.signal.value == "SUCCESS")
    logger.event(
        f"[PLANNER_EXECUTOR] ✅ Done — {successful}/{len(worker_results)} steps succeeded, {len(output)} chars."
    )

    return ExecutionResult(
        pattern_used=PatternType.PLANNER_EXECUTOR,
        query=query,
        output=output,
        steps_taken=len(worker_results) + 1,
        success=successful > 0,
        analysis=analysis,
        worker_results=worker_results,
        steps=steps,
        token_usage=usage,
    )


async def _synthesize(
    agent: dict,
    query: str,
    worker_results: list,
) -> str:
    """Manager LLM synthesizes all execution steps into a final answer."""
    steps_text = "\n\n".join(
        [
            f"Step {i + 1} — {r.worker_id} | Status: {r.signal.value}\nTask  : {r.task[:120]}\nResult: {r.output}"
            for i, r in enumerate(worker_results)
        ]
    )

    try:
        _timeout = agent.get("llm_timeout", 120.0)
        resp = await asyncio.wait_for(
            agent["llm"].ainvoke(
                [
                    SystemMessage(content=SYNTHESIS_PROMPT),
                    HumanMessage(
                        content=(
                            f"Original query: {query}\n\n"
                            f"Execution steps:\n{steps_text}\n\n"
                            f"Synthesize all results into a comprehensive final answer:"
                        )
                    ),
                ]
            ),
            timeout=_timeout,
        )
        logger.event(f"[PLANNER_EXECUTOR] Synthesis done — {len(resp.content)} chars.")
        return resp.content
    except Exception as e:
        logger.error(f"[PLANNER_EXECUTOR] Synthesis failed: {e}")
        successful = [r for r in worker_results if r.signal.value == "SUCCESS"]
        return successful[-1].output if successful else "All execution steps failed."
