"""Blackboard pattern — shared mutable state with specialist Knowledge Sources."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from langchain_core.messages import HumanMessage

from .. import worker as worker_module
from ..llm_streaming import astream_llm_to_event_queue
from ..worker import extend_invoke_config_with_event_queue
from ..logging_utils import get_logger
from ..models import (
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    SignalType,
    StepType,
    WorkerResult,
    _extract_token_usage,
    _make_step,
    _merge_token_usage,
)
from ._blackboard_state import BlackboardState
from ._resolve import resolve_worker_configs
from .worker_gates import drain_for_halt, get_signal_queue

logger = get_logger(__name__)

MAX_ROUNDS = 10  # safety ceiling — prevents infinite loops on unsatisfiable deps

BLACKBOARD_SYNTHESIS_PROMPT = """\
You are a synthesis expert. Multiple specialist agents have contributed to
a shared blackboard to solve the goal below.

{board_snapshot}

Your task:
- Integrate ALL filled slots into a single coherent, well-structured response
- Resolve any contradictions or overlaps across slots
- Preserve key insights from each specialist
- Do NOT simply concatenate — synthesise into a unified answer
- Address the original GOAL directly

Provide the final integrated answer now."""


async def handle_blackboard(
    agent: Any,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Resolve KS configs, initialise board with empty slots, then loop:
    pick eligible KS → inject board snapshot → run → write slot.
    Failed KS get a failure marker so dependents aren't permanently blocked.
    L4 HALT_ALL checked after each KS. Synthesizes from filled board.
    """
    agent_name = agent.get("name", "Agent")
    llm = agent["llm"]
    ml = agent.get("max_step_output_length", 0)
    signal_queue = get_signal_queue(agent, config)
    steps: list = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    raw_messages: list = []

    logger.event(f"[Blackboard] {agent_name} — query={query[:60]}... ks_count={len(analysis.subtasks)}")

    if not analysis.subtasks:
        logger.warning(f"[Blackboard] {agent_name} — no subtasks, returning empty.")
        return ExecutionResult(
            pattern_used=PatternType.BLACKBOARD,
            query=query,
            output="No Knowledge Sources could be planned for this query.",
            steps_taken=1,
            success=False,
            analysis=analysis,
            steps=steps,
            messages=raw_messages,
        )

    ks_configs = resolve_worker_configs(agent, analysis.subtasks)

    slots = {cfg.worker_id: None for cfg in ks_configs}
    board = BlackboardState(goal=query, slots=slots)

    worker_results: list[WorkerResult] = []
    halt_triggered = False

    for round_num in range(MAX_ROUNDS):
        board.round = round_num

        eligible = [
            cfg
            for cfg in ks_configs
            if cfg.worker_id not in board.filled and all(dep in board.filled for dep in cfg.depends_on)
        ]

        if not eligible:
            logger.event(
                f"[Blackboard] Round {round_num} — "
                f"no eligible KS (board={'complete' if board.is_complete() else 'stuck'}). "
                f"Stopping."
            )
            break

        logger.event(
            f"[Blackboard] Round {round_num} — "
            f"eligible KS: {[c.worker_id for c in eligible]}, "
            f"filled: {list(board.filled)}"
        )

        for ks_cfg in eligible:
            snapshot = board.snapshot()
            enriched_cfg = ks_cfg.model_copy(
                update={
                    "context": {
                        **ks_cfg.context,
                        "board_snapshot": snapshot,
                        "goal": query,
                    }
                }
            )

            logger.event(f"[Blackboard] Running KS '{ks_cfg.worker_id}' (round {round_num})")
            merged = extend_invoke_config_with_event_queue(config, agent.get("_event_queue"))
            result = await worker_module.run_worker(enriched_cfg, llm, invoke_config=merged)
            worker_results.append(result)
            raw_messages.extend(getattr(result, "messages", []))
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

            if result.signal == SignalType.SUCCESS:
                board.write(ks_cfg.worker_id, result.output, ks_cfg.worker_id)
                logger.event(f"[Blackboard] Slot '{ks_cfg.worker_id}' filled — {len(result.output)} chars.")
            else:
                failure_marker = f"FAILED: {result.error or 'unknown error'}"
                board.write(ks_cfg.worker_id, failure_marker, ks_cfg.worker_id)
                logger.warning(
                    f"[Blackboard] KS '{ks_cfg.worker_id}' failed: {result.error} — wrote failure marker to board."
                )

            if signal_queue:
                halt = await drain_for_halt(
                    signal_queue,
                    caller_name=f"{agent_name}[Blackboard]",
                    user_callback=agent.get("user_callback"),
                    clarification_queues=(config.get("configurable", {}).get("clarification_queues") if config else {}),
                )
                if halt:
                    logger.warning(
                        f"[Blackboard] HALT_ALL after KS '{ks_cfg.worker_id}' "
                        f"(round {round_num}) — stopping board execution."
                    )
                    halt_triggered = True
                    break

        if halt_triggered or board.is_complete():
            if board.is_complete():
                logger.event(f"[Blackboard] Board complete after round {round_num}.")
            break

    else:
        logger.warning(
            f"[Blackboard] MAX_ROUNDS ({MAX_ROUNDS}) reached — "
            f"board not complete. "
            f"Filled: {list(board.filled)}, "
            f"Unfilled: {board.unfilled_slots()}"
        )

    rounds = board.round + 1

    successful = [r for r in worker_results if r.signal == SignalType.SUCCESS]

    if not successful:
        return ExecutionResult(
            pattern_used=PatternType.BLACKBOARD,
            query=query,
            output=("All Knowledge Sources failed — no board content to synthesize."),
            steps_taken=len(worker_results),
            success=False,
            analysis=analysis,
            worker_results=worker_results,
            metadata={
                "rounds_used": rounds,
                "slots_filled": list(board.filled),
                "slots_unfilled": board.unfilled_slots(),
                "board_history": board.history,
                "halt_triggered": halt_triggered,
            },
            steps=steps,
            token_usage=usage,
            messages=raw_messages,
        )

    synthesis_prompt = BLACKBOARD_SYNTHESIS_PROMPT.format(board_snapshot=board.snapshot())
    synth_input = [HumanMessage(content=synthesis_prompt)]
    try:
        _timeout = agent.get("llm_timeout", 120.0) if isinstance(agent, dict) else 120.0
        t_synth = time.perf_counter()
        event_queue = agent.get("_event_queue")
        if event_queue is not None:
            synthesis, last_chunk = await astream_llm_to_event_queue(
                llm, synth_input, event_queue, timeout=_timeout
            )
            raw_messages.extend(synth_input)
            if last_chunk is not None:
                raw_messages.append(last_chunk)
            synthesis = synthesis.strip()
            synth_usage = _extract_token_usage(last_chunk) if last_chunk else {}
        else:
            response = await asyncio.wait_for(
                llm.ainvoke(synth_input),
                timeout=_timeout,
            )
            raw_messages.extend(synth_input)
            raw_messages.append(response)
            synthesis = response.content.strip()
            synth_usage = _extract_token_usage(response)
        synth_ms = round((time.perf_counter() - t_synth) * 1000, 1)
        if synth_usage:
            usage = _merge_token_usage(usage, synth_usage)
        steps.append(
            _make_step(
                StepType.LLM_CALL,
                "blackboard_synthesis",
                input=query,
                output=synthesis,
                duration_ms=synth_ms,
                max_length=ml,
            )
        )
        logger.event(f"[Blackboard] Synthesis done — {len(synthesis)} chars.")
    except Exception as exc:
        logger.error(f"[Blackboard] Synthesis LLM failed: {exc}")
        raw_messages.extend(synth_input)
        synthesis = "\n\n".join(f"[{r.worker_id}]: {r.output}" for r in successful)

    logger.event(
        f"[Blackboard] {agent_name} — done. "
        f"{len(successful)}/{len(worker_results)} KSes succeeded, "
        f"{rounds} round(s), {len(synthesis)} chars."
    )

    return ExecutionResult(
        pattern_used=PatternType.BLACKBOARD,
        query=query,
        output=synthesis,
        success=len(successful) > 0,
        steps_taken=len(worker_results),
        analysis=analysis,
        worker_results=worker_results,
        metadata={
            "rounds_used": rounds,
            "slots_filled": list(board.filled),
            "slots_unfilled": board.unfilled_slots(),
            "board_history": board.history,
            "halt_triggered": halt_triggered,
        },
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )
