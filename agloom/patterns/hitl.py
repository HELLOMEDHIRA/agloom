"""L3+L4 HITL execution engine for parallel worker patterns (Supervisor, Swarm, Hybrid DAG)."""

from __future__ import annotations

import asyncio

from .. import worker as worker_module
from ..hitl_contract import HITLEvent, call_user_callback
from ..logging_utils import get_logger
from ..models import ResolvedWorkerConfig, Signal, SignalType, WorkerResult
from ..worker import extend_invoke_config_with_event_queue
from .worker_gates import get_signal_queue

logger = get_logger(__name__)


async def run_workers_with_hitl(
    agent: dict,
    configs: list[ResolvedWorkerConfig],
    invoke_config: dict | None = None,
    halt_event: asyncio.Event | None = None,
) -> tuple[list[WorkerResult], list[str]]:
    """
    L3-before gate → parallel execution with L4 signal listener → L3-after gate.
    If halt_event is None, creates a local one; HYBRID_DAG shares one across levels.
    Returns (results, skipped_ids).
    """
    if halt_event is None:
        halt_event = asyncio.Event()

    if halt_event.is_set():
        logger.warning("[HITL] halt_event already set — skipping all workers.")
        return [], [cfg.worker_id for cfg in configs]

    approved, skipped_ids = await _check_before_workers(agent, configs)
    if not approved:
        logger.event(f"[HITL] All workers skipped by L3-before: {skipped_ids}")
        return [], skipped_ids

    results = await _run_parallel_workers(
        agent=agent,
        configs=approved,
        invoke_config=invoke_config,
        halt_event=halt_event,
    )

    return results, skipped_ids


async def _check_before_workers(
    agent: dict,
    configs: list[ResolvedWorkerConfig],
) -> tuple[list[ResolvedWorkerConfig], list[str]]:
    """Gate each worker against interrupt_before_workers. 'workers' = wildcard."""
    interrupt_list: list[str] = agent.get("interrupt_before_workers") or []
    user_callback = agent.get("user_callback")

    if not interrupt_list or not user_callback:
        return configs, []

    approved: list[ResolvedWorkerConfig] = []
    skipped: list[str] = []

    for cfg in configs:
        if not _should_interrupt(cfg.worker_id, interrupt_list):
            approved.append(cfg)
            continue

        logger.event(f"[HITL] L3-Before: pausing before '{cfg.worker_id}'")
        try:
            decision = await call_user_callback(
                user_callback,
                HITLEvent.WORKER_INTERRUPT_BEFORE,
                (
                    f"Agent   : {agent.get('name', 'Agent')}\n"
                    f"Worker  : {cfg.worker_id}\n"
                    f"Task    : {cfg.task}\n"
                    f"Tools   : {[t.name for t in cfg.tools] if cfg.tools else 'LLM-only'}\n"
                    "\nType 'continue' to proceed, 'skip' to abort this worker."
                ),
            )
        except Exception as exc:
            logger.error(f"[HITL] L3-Before: callback raised {exc} — skipping '{cfg.worker_id}' for safety.")
            decision = "skip"

        if str(decision).strip().lower() in ("skip", "abort", "no", "cancel"):
            logger.event(f"[HITL] L3-Before: '{cfg.worker_id}' skipped by user.")
            skipped.append(cfg.worker_id)
        else:
            logger.event(f"[HITL] L3-Before: '{cfg.worker_id}' approved.")
            approved.append(cfg)

    return approved, skipped


async def _run_parallel_workers(
    agent: dict,
    configs: list[ResolvedWorkerConfig],
    invoke_config: dict | None,
    halt_event: asyncio.Event,
) -> list[WorkerResult]:
    """
    Spawn every config as an asyncio.Task (not gather) for individual
    cancellability. Semaphore throttles concurrency.
    """
    max_concurrent = agent.get("max_concurrent", 4)
    try:
        mc = int(max_concurrent)
    except (TypeError, ValueError):
        mc = 4
    if mc < 1:
        mc = 4
    semaphore = asyncio.Semaphore(mc)
    llm = agent["llm"]

    async def _run_one(cfg: ResolvedWorkerConfig) -> WorkerResult:
        async with semaphore:
            if halt_event.is_set():
                return WorkerResult(
                    worker_id=cfg.worker_id,
                    task=cfg.task,
                    output="Skipped — HALT_ALL fired before this worker started.",
                    signal=SignalType.FAILED,
                    error="HALT_ALL",
                )
            merged = extend_invoke_config_with_event_queue(invoke_config, agent.get("_event_queue"))
            return await worker_module.run_worker(cfg, llm, invoke_config=merged)

    tasks: dict[asyncio.Task, ResolvedWorkerConfig] = {asyncio.create_task(_run_one(cfg)): cfg for cfg in configs}

    signal_task = asyncio.create_task(
        _listen_for_halt(
            agent=agent,
            tasks=list(tasks.keys()),
            halt_event=halt_event,
            invoke_config=invoke_config,  # configurable.clarification_queues for L4 answers
        )
    )

    results = await _collect_with_after_interrupt(agent, tasks, halt_event)

    signal_task.cancel()
    try:
        await signal_task
    except asyncio.CancelledError:
        pass

    return results


async def _listen_for_halt(
    agent: dict,
    tasks: list[asyncio.Task],
    halt_event: asyncio.Event,
    invoke_config: dict | None = None,
) -> None:
    """
    Background drain of signal_queue. HALT_ALL cancels all tasks.
    CLARIFICATION_REQUEST routes through user_callback to per-worker queues
    without blocking other workers.
    """
    signal_queue = get_signal_queue(agent, invoke_config)
    if signal_queue is None:
        return

    clarification_queues: dict[str, asyncio.Queue] = {}
    if invoke_config:
        clarification_queues = invoke_config.get("configurable", {}).get("clarification_queues") or {}

    user_callback = agent.get("user_callback")
    agent_name = agent.get("name", "Agent")

    while not all(t.done() for t in tasks):
        try:
            raw = await asyncio.wait_for(signal_queue.get(), timeout=0.2)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            return

        if not isinstance(raw, Signal):
            logger.warning(
                f"[HITL] Ignoring non-Signal queue item: {type(raw).__name__!r} — "
                f"agent={agent_name!r}"
            )
            continue
        signal = raw

        if signal.signal_type == SignalType.HALT_ALL:
            logger.warning(
                f"[HITL] L4 HALT_ALL — worker={signal.worker_id!r} "
                f"msg={signal.message!r} — cancelling {len(tasks)} task(s)."
            )
            halt_event.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            return

        if signal.signal_type == SignalType.CLARIFICATION_REQUEST:
            logger.event(f"[HITL] L4 CLARIFICATION_REQUEST from {signal.worker_id!r} — question={signal.message!r}")

            if not user_callback:
                logger.warning(
                    f"[HITL] No user_callback registered — worker '{signal.worker_id}' will timeout in tool."
                )
                continue

            cq = clarification_queues.get(signal.worker_id)
            if cq is None:
                logger.warning(
                    f"[HITL] No clarification queue for '{signal.worker_id}' — "
                    f"worker may not have registered (tool not injected?)."
                )
                continue

            try:
                answer = await call_user_callback(
                    user_callback,
                    HITLEvent.CLARIFICATION_REQUEST,
                    {
                        "agent_name": agent_name,
                        "worker_id": signal.worker_id,
                        "question": signal.message,
                    },
                )
                logger.event(f"[HITL] Clarification answered for '{signal.worker_id}': {str(answer)!r}")
                await cq.put(str(answer))

            except Exception as exc:
                logger.error(
                    f"[HITL] user_callback raised during clarification: {exc} — "
                    f"sending fallback answer to worker '{signal.worker_id}'."
                )
                await cq.put(f"Clarification request failed ({exc}). Proceed with your best judgment.")

        else:
            logger.debug(f"[HITL] L4 signal ignored: {signal.signal_type}")


async def _collect_with_after_interrupt(
    agent: dict,
    tasks: dict[asyncio.Task, ResolvedWorkerConfig],
    halt_event: asyncio.Event,
) -> list[WorkerResult]:
    """Collect results as workers complete (FIRST_COMPLETED), with L3-after gate."""
    interrupt_list: list[str] = agent.get("interrupt_after_workers") or []
    user_callback = agent.get("user_callback")
    agent_name = agent.get("name", "Agent")

    pending = set(tasks.keys())
    results: list[WorkerResult] = []

    while pending:
        if halt_event.is_set():
            for t in pending:
                t.cancel()
            for t in pending:
                cfg = tasks[t]
                try:
                    r = await t
                except asyncio.CancelledError:
                    r = WorkerResult(
                        worker_id=cfg.worker_id,
                        task=cfg.task,
                        output="Cancelled — HALT_ALL fired.",
                        signal=SignalType.FAILED,
                        error="CancelledError",
                    )
                results.append(r)
            break

        done, pending = await asyncio.wait(
            pending,
            return_when=asyncio.FIRST_COMPLETED,
            timeout=0.3,
        )

        for task in done:
            cfg = tasks[task]
            try:
                result = await task
            except asyncio.CancelledError:
                result = WorkerResult(
                    worker_id=cfg.worker_id,
                    task=cfg.task,
                    output="Cancelled — HALT_ALL fired.",
                    signal=SignalType.FAILED,
                    error="CancelledError",
                )
            except Exception as exc:
                result = WorkerResult(
                    worker_id=cfg.worker_id,
                    task=cfg.task,
                    output=f"Worker raised unexpected exception: {exc}",
                    signal=SignalType.FAILED,
                    error=str(exc),
                )

            if interrupt_list and user_callback and _should_interrupt(cfg.worker_id, interrupt_list):
                logger.event(f"[HITL] L3-After: pausing after '{cfg.worker_id}'")
                try:
                    await call_user_callback(
                        user_callback,
                        HITLEvent.WORKER_INTERRUPT_AFTER,
                        (
                            f"Agent  : {agent_name}\n"
                            f"Worker : {cfg.worker_id} completed.\n"
                            f"Task   : {cfg.task}\n"
                            f"Result : {result.output}\n"
                            f"Status : {result.signal.value}"
                        ),
                    )
                except Exception as exc:
                    logger.error(f"[HITL] L3-After callback raised: {exc}")

            results.append(result)

    return results


def _should_interrupt(worker_id: str, interrupt_list: list[str]) -> bool:
    return "workers" in interrupt_list or worker_id in interrupt_list
