"""L3+L4 HITL execution engine for parallel worker patterns (Supervisor, Swarm, Hybrid DAG)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, cast

from .. import worker as worker_module
from ..hitl_contract import HITLEvent, call_user_callback
from ..logging_utils import get_logger
from ..models import ResolvedWorkerConfig, Signal, SignalType, WorkerResult
from ..worker import extend_invoke_config_with_event_queue
from ._worker_signals import halted_worker_result
from .worker_gates import get_signal_queue

logger = get_logger(__name__)

# Bounded join when awaiting worker tasks (cancelled workers should finish quickly; guard hangs).
_TASK_JOIN_TIMEOUT_S = 600.0
_SIGNAL_POLL_TIMEOUT_S = 0.2
_SIGNAL_POLL_TIMEOUT = object()  # sentinel from _timed_signal_get on queue timeout


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
    """Gate each worker against interrupt_before_workers.

    Wildcards: ``*`` or ``__all__`` matches every worker id. The string ``workers`` is a **literal**
    worker id only (not a wildcard — use ``*`` for all workers).
    """
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
            logger.error(
                f"[HITL] L3-Before: callback raised {exc!r} — failing open (continue with worker); "
                f"not treating as user skip."
            )
            approved.append(cfg)
            continue

        if str(decision).strip().lower() in ("skip", "abort", "no", "cancel"):
            # Same user-decline contract as L2 UserAbort / middleware skip: not an execution failure bit.
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
            merged = extend_invoke_config_with_event_queue(invoke_config, agent.get("_event_queue"), agent=agent)
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


async def _timed_signal_get(signal_queue: asyncio.Queue) -> Any:
    """Return the next queue item, or :data:`_SIGNAL_POLL_TIMEOUT` after a short idle window."""
    try:
        return await asyncio.wait_for(signal_queue.get(), timeout=_SIGNAL_POLL_TIMEOUT_S)
    except TimeoutError:
        return _SIGNAL_POLL_TIMEOUT


async def _apply_l4_signal_batch(
    *,
    agent: dict,
    agent_name: str,
    batch: list[Any],
    tasks: list[asyncio.Task],
    halt_event: asyncio.Event,
    clarification_queues: dict[str, asyncio.Queue],
    user_callback: Any,
) -> bool:
    """Process one drained batch. Returns True when HALT_ALL fired (listener should exit)."""
    halts = [x for x in batch if isinstance(x, Signal) and x.signal_type == SignalType.HALT_ALL]
    if halts:
        sig = halts[0]
        logger.warning(
            f"[HITL] L4 HALT_ALL — worker={sig.worker_id!r} "
            f"msg={sig.message!r} — cancelling {len(tasks)} task(s)."
        )
        halt_event.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        return True

    for raw in batch:
        if not isinstance(raw, Signal):
            logger.warning(
                f"[HITL] Ignoring non-Signal queue item: {type(raw).__name__!r} — "
                f"agent={agent_name!r}"
            )
            continue
        signal = raw

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
                await cq.put(
                    "Clarification could not be collected. Proceed with your best judgment."
                )

        else:
            logger.debug(f"[HITL] L4 signal ignored: {signal.signal_type}")
    return False


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

    pending_workers = {t for t in tasks if not t.done()}
    poll_task: asyncio.Task[Any] | None = None

    try:
        while pending_workers:
            if poll_task is None or poll_task.done():
                poll_task = asyncio.create_task(_timed_signal_get(signal_queue))

            done, still = await asyncio.wait(
                pending_workers | {poll_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            pending_workers = {t for t in still if t is not poll_task and not t.done()}

            if poll_task not in done:
                continue

            item = poll_task.result()
            poll_task = None
            if item is _SIGNAL_POLL_TIMEOUT:
                continue

            batch = [item]
            while True:
                try:
                    batch.append(signal_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if await _apply_l4_signal_batch(
                agent=agent,
                agent_name=agent_name,
                batch=batch,
                tasks=tasks,
                halt_event=halt_event,
                clarification_queues=clarification_queues,
                user_callback=user_callback,
            ):
                return
    except asyncio.CancelledError:
        return
    finally:
        if poll_task is not None and not poll_task.done():
            poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poll_task


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
                    r = cast(
                        WorkerResult,
                        await asyncio.wait_for(asyncio.shield(t), timeout=_TASK_JOIN_TIMEOUT_S),
                    )
                except asyncio.TimeoutError:
                    r = halted_worker_result(
                        worker_id=cfg.worker_id,
                        task=cfg.task,
                        output="Timed out waiting for worker task after HALT_ALL.",
                        error="TaskJoinTimeout",
                    )
                except asyncio.CancelledError:
                    r = halted_worker_result(
                        worker_id=cfg.worker_id,
                        task=cfg.task,
                        output="Cancelled — HALT_ALL fired.",
                        error="CancelledError",
                    )
                results.append(r)
            break

        # Wake as soon as any worker finishes or HALT_ALL sets the event (no fixed polling delay).
        halt_wait = asyncio.create_task(halt_event.wait())
        try:
            done, unfinished = await asyncio.wait(
                frozenset(pending) | {halt_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            if not halt_wait.done():
                halt_wait.cancel()
                try:
                    await halt_wait
                except asyncio.CancelledError:
                    pass

        pending = {t for t in unfinished if t is not halt_wait}
        halt_done = halt_wait in done

        for task in done:
            if task is halt_wait:
                continue
            cfg = tasks[task]
            try:
                result = cast(
                    WorkerResult,
                    await asyncio.wait_for(asyncio.shield(task), timeout=_TASK_JOIN_TIMEOUT_S),
                )
            except asyncio.TimeoutError:
                result = WorkerResult(
                    worker_id=cfg.worker_id,
                    task=cfg.task,
                    output="Timed out waiting for worker task to finish.",
                    signal=SignalType.FAILED,
                    error="TaskJoinTimeout",
                )
            except asyncio.CancelledError:
                result = halted_worker_result(
                    worker_id=cfg.worker_id,
                    task=cfg.task,
                    output="Cancelled — HALT_ALL fired.",
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

        if halt_done:
            continue

    return results


_HITL_WORKERS_LITERAL_WARNED = False


def _should_interrupt(worker_id: str, interrupt_list: list[str]) -> bool:
    global _HITL_WORKERS_LITERAL_WARNED
    tokens = {x.strip() for x in interrupt_list if x.strip()}
    if "*" in tokens or "__all__" in tokens:
        return True
    if "workers" in tokens and not _HITL_WORKERS_LITERAL_WARNED:
        _HITL_WORKERS_LITERAL_WARNED = True
        logger.warning(
            "[HITL] interrupt_* list contains 'workers', which is not a wildcard "
            "(use '*' or '__all__' for all workers). Only a worker whose id is literally "
            "'workers' will match."
        )
    return worker_id in tokens
