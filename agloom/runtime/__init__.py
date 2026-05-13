"""Agloom runtime — asyncio execution platform for agents (local-first).

Ships a fully functional in-process runtime with:
- ``RuntimeNode`` — top-level assembly (scheduler + pool + registry)
- ``WorkerPool``  — manages worker lifecycle + health monitoring
- ``LocalAIWorker`` — wraps UnifiedAgent for in-process execution
- ``InProcessScheduler`` — asyncio priority-queue dispatcher
- ``InMemoryRegistry`` — worker capability registry

Programmatic use::

    from agloom import create_agent
    from agloom.runtime import RuntimeNode
    from agloom.protocol import AsyncSessionEmitter

    agent = await create_agent(model=llm)
    emitter = AsyncSessionEmitter(session_id="s_01", writer=sys.stdout.write)
    node = RuntimeNode.create_local(agent=agent, emitter=emitter)
    await node.start()

    task_id = await node.submit_invoke(
        prompt="Read pyproject.toml",
        thread="t_abc",
        session="s_01",
    )

    await node.stop()

Stdio / WebSocket serve (CLI)::

    agloom-runtime serve --transport=stdio
    agloom-runtime serve --transport=ws --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

from .bridge import new_session_id, run_invocation, run_invocation_to_writer
from .hitl import HITLBridge
from .node import RuntimeNode
from .pool import WorkerPool
from .registry import InMemoryRegistry, WorkerRegistry
from .scheduler import InProcessScheduler, Scheduler, SchedulerFullError
from .translator import translate
from .workers import BaseWorker
from .workers.local import LocalAIWorker
from .workers.types import (
    RetryPolicy,
    TaskStatus,
    WorkerHealth,
    WorkerStatus,
    WorkerTask,
    WorkerType,
)

__all__ = [
    # Legacy helpers (kept for backward compat)
    "HITLBridge",
    "new_session_id",
    "run_invocation",
    "run_invocation_to_writer",
    "translate",
    # Runtime node
    "RuntimeNode",
    # Worker pool
    "WorkerPool",
    # Workers
    "BaseWorker",
    "LocalAIWorker",
    # Scheduler
    "Scheduler",
    "InProcessScheduler",
    "SchedulerFullError",
    # Registry
    "WorkerRegistry",
    "InMemoryRegistry",
    # Data models
    "WorkerTask",
    "WorkerHealth",
    "WorkerStatus",
    "WorkerType",
    "TaskStatus",
    "RetryPolicy",
]
