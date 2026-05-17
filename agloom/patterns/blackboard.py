"""Blackboard pattern — shared mutable state with specialist Knowledge Sources."""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from langchain_core.messages import HumanMessage

from .. import worker as worker_module
from ..llm_streaming import stream_or_invoke_llm
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
from ..worker import extend_invoke_config_with_event_queue
from ._blackboard_state import BlackboardState
from ._resolve import resolve_worker_configs
from ._steps_accounting import steps_taken_from_audit
from ._synthesis_contract import ALL_PATTERN_WORKERS_FAILED_ERROR, pattern_synthesis_success
from .worker_gates import await_with_halt_polling, drain_for_halt, get_signal_queue

logger = get_logger(__name__)

MAX_ROUNDS = 10  # default safety ceiling — prevents infinite loops on unsatisfiable deps

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
    max_rounds: int | None = None,
) -> ExecutionResult:
    """
    Resolve KS configs, initialise board with empty slots, then loop:
    pick eligible KS → inject board snapshot → run → write slot.
    Failed KS are marked attempted (not filled) so dependents unblock.
    sequential runners only observe ``HALT_ALL`` between worker steps (see
    :mod:`agloom.patterns._sequential`).

    *max_rounds* overrides the module-level ``MAX_ROUNDS`` constant for this invocation,
    allowing callers to adjust the ceiling without monkey-patching the global.
    """
    _max_rounds = max_rounds if max_rounds is not None else MAX_ROUNDS
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

    for round_num in range(_max_rounds):
        board.round = round_num

        eligible = [
            cfg
            for cfg in ks_configs
            if cfg.worker_id not in board.attempted
            and all(dep in board.attempted for dep in cfg.depends_on)
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
            if signal_queue:
                halt = await drain_for_halt(
                    signal_queue,
                    caller_name=f"{agent_name}[Blackboard]",
                    user_callback=agent.get("user_callback"),
                    clarification_queues=(
                        config.get("configurable", {}).get("clarification_queues") if config else {}
                    ),
                )
                if halt:
                    logger.warning(f"[Blackboard] HALT_ALL before KS '{ks_cfg.worker_id}' — stopping.")
                    halt_triggered = True
                    break

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
            merged = extend_invoke_config_with_event_queue(config, agent.get("_event_queue"), agent=agent)
            clar_qs = (config.get("configurable", {}).get("clarification_queues") if config else {}) or {}
            worker_task = asyncio.create_task(
                worker_module.run_worker(enriched_cfg, llm, invoke_config=merged)
            )
            run_out, halted_mid = await await_with_halt_polling(
                worker_task,
                signal_queue=signal_queue,
                caller_name=f"{agent_name}[Blackboard]",
                user_callback=agent.get("user_callback"),
                clarification_queues=clar_qs,
            )
            if halted_mid:
                result = WorkerResult(
                    worker_id=ks_cfg.worker_id,
                    task=enriched_cfg.task,
                    output="Cancelled — HALT_ALL during Knowledge Source run.",
                    signal=SignalType.HALTED,
                    error="HALT_ALL",
                )
            else:
                result = cast(WorkerResult, run_out)
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
                board.mark_failed(
                    ks_cfg.worker_id,
                    result.error or "unknown error",
                    ks_cfg.worker_id,
                )
                logger.warning(
                    f"[Blackboard] KS '{ks_cfg.worker_id}' failed: {result.error} — slot marked failed."
                )

            if halted_mid:
                halt_triggered = True
                break

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
            f"[Blackboard] MAX_ROUNDS ({_max_rounds}) reached — "
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
            steps_taken=steps_taken_from_audit(steps),
            success=False,
            analysis=analysis,
            worker_results=worker_results,
            error=ALL_PATTERN_WORKERS_FAILED_ERROR,
            metadata={
                "rounds_used": rounds,
                "slots_filled": list(board.filled),
                "slots_failed": list(board.failed),
                "slots_unfilled": board.unfilled_slots(),
                "board_history": board.history,
                "halt_triggered": halt_triggered,
            },
            steps=steps,
            token_usage=usage,
            messages=raw_messages,
        )

    synthesis_prompt = BLACKBOARD_SYNTHESIS_PROMPT.replace(
        "{board_snapshot}", board.synthesis_snapshot()
    )
    synth_input = [HumanMessage(content=synthesis_prompt)]
    synthesis_degraded = False
    synthesis_error: str | None = None
    synthesis = ""
    try:
        _timeout = agent.get("llm_timeout", 120.0) if isinstance(agent, dict) else 120.0
        t_synth = time.perf_counter()
        synthesis, tail, last_chunk = await stream_or_invoke_llm(
            llm, synth_input, agent, timeout=_timeout, phase="blackboard_synthesis"
        )
        raw_messages.extend(tail)
        synth_usage = _extract_token_usage(last_chunk) if last_chunk else {}
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
                usage=synth_usage,
                phase="blackboard_synthesis",
            )
        )
        logger.event(f"[Blackboard] Synthesis done — {len(synthesis)} chars.")
    except Exception as exc:
        logger.error(f"[Blackboard] Synthesis LLM failed: {exc}")
        synthesis_degraded = True
        synthesis_error = "SynthesisFailed"
        raw_messages.extend(synth_input)
        synthesis = "\n\n".join(f"[{r.worker_id}]: {r.output}" for r in successful)
        steps.append(
            _make_step(
                StepType.LLM_CALL,
                "blackboard_synthesis",
                input=query,
                output=synthesis,
                max_length=ml,
                phase="blackboard_synthesis",
                synthesis_error=str(exc),
            )
        )

    logger.event(
        f"[Blackboard] {agent_name} — done. "
        f"{len(successful)}/{len(worker_results)} KSes succeeded, "
        f"{rounds} round(s), {len(synthesis)} chars."
    )

    from ..orchestrator.hooks import maybe_spawn_conflict_resolution

    slot_outputs = [r.output for r in successful]
    swarm_resolution = await maybe_spawn_conflict_resolution(
        agent,
        config,
        query,
        slot_outputs,
        target_pattern=PatternType.SWARM,
    )
    if swarm_resolution is not None and swarm_resolution.success:
        synthesis = swarm_resolution.output
        usage = _merge_token_usage(usage, swarm_resolution.token_usage)
        steps.extend(swarm_resolution.steps)

    return ExecutionResult(
        pattern_used=PatternType.BLACKBOARD,
        query=query,
        output=synthesis,
        success=pattern_synthesis_success(worker_results=worker_results, synthesis_degraded=synthesis_degraded),
        steps_taken=steps_taken_from_audit(steps),
        analysis=analysis,
        worker_results=worker_results,
        error=synthesis_error,
        metadata={
            "rounds_used": rounds,
            "slots_filled": list(board.filled),
            "slots_failed": list(board.failed),
            "slots_unfilled": board.unfilled_slots(),
            "board_history": board.history,
            "halt_triggered": halt_triggered,
            "synthesis_degraded": synthesis_degraded,
        },
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )
