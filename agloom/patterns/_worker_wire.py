"""Shared worker lifecycle wire events (supervisor / swarm / DAG parity)."""

from __future__ import annotations

from typing import Any

from ..src.models import AgentEvent, StepType, _make_step, _trunc


async def emit_worker_start(
    agent: dict,
    *,
    worker_id: str,
    task: str,
    steps: list,
    max_length: int = 0,
) -> None:
    steps.append(_make_step(StepType.WORKER_START, worker_id, input=task, max_length=max_length))
    eq = agent.get("_event_queue")
    if eq is not None:
        await eq.put(
            AgentEvent(
                type="worker_start",
                data={"name": worker_id, "input": _trunc(task, max_length)},
            )
        )


async def emit_worker_end(
    agent: dict,
    *,
    worker_id: str,
    task: str,
    output: str,
    duration_ms: float,
    signal: str,
    steps: list,
    max_length: int = 0,
    worker_steps: list | None = None,
) -> None:
    eq = agent.get("_event_queue")
    if worker_steps:
        for step in worker_steps:
            if step.type not in (StepType.TOOL_CALL, StepType.TOOL_RESULT):
                continue
            steps.append(step)
            if eq is not None and not (
                step.metadata.get("wire_emitted") or step.metadata.get("_wire_emitted")
            ):
                event_type = "tool_call" if step.type == StepType.TOOL_CALL else "tool_result"
                await eq.put(
                    AgentEvent(
                        type=event_type,
                        data={
                            "worker_id": worker_id,
                            "name": step.name,
                            "input": step.input,
                            "output": step.output,
                            **step.metadata,
                        },
                    )
                )
    steps.append(
        _make_step(
            StepType.WORKER_END,
            worker_id,
            input=task,
            output=output,
            duration_ms=duration_ms,
            signal=signal,
            max_length=max_length,
        )
    )
    if eq is not None:
        await eq.put(
            AgentEvent(
                type="worker_end",
                data={
                    "name": worker_id,
                    "input": _trunc(task, max_length),
                    "output": _trunc(output, max_length),
                    "duration_ms": duration_ms,
                    "signal": signal,
                },
            )
        )
