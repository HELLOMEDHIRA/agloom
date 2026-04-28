"""Delegation between agents: ``HandoffTarget``, background tasks, ``make_agent_tool``.

Handoff targets feed classifier context; ``run_delegate`` / ``resolve_handoff`` execute
or select a delegate. ``BackgroundDelegationManager`` lives on ``config["_bg_delegation_manager"]``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .logging_utils import get_logger
from .models import ExecutionResult

logger = get_logger(__name__)


class HandoffTarget:
    """Routes work to another agent (``UnifiedAgent`` or compatible).

    Attributes:
        agent: Callee with ``ainvoke``.
        name: Stable id for ``resolve_handoff`` / classifier text (defaults to ``agent.name``).
        description: Shown in classifier delegate list; should say what to send here.
        filter_fn: Optional predicate on query (sync or async); if false, target skipped.
        input_transform: Optional query rewrite before ``ainvoke`` (sync or async).
    """

    __slots__ = ("agent", "description", "filter_fn", "input_transform", "name")

    def __init__(
        self,
        agent: Any,
        *,
        name: str | None = None,
        description: str = "",
        filter_fn: Callable[[str], bool] | None = None,
        input_transform: Callable[[str], str] | None = None,
    ) -> None:
        self.agent = agent
        self.name = name or getattr(agent, "name", "delegate")
        self.description = description
        self.filter_fn = filter_fn
        self.input_transform = input_transform

    def __repr__(self) -> str:
        return f"HandoffTarget(name={self.name!r}, description={self.description[:60]!r})"


def _build_delegation_context(targets: list[HandoffTarget]) -> str:
    """Classifier prompt fragment listing named delegates."""
    if not targets:
        return ""

    lines = ["AVAILABLE DELEGATES", "=" * 55, ""]
    for t in targets:
        desc = t.description or f"Delegate agent: {t.name}"
        lines.append(f"  - [{t.name}] {desc}")
    lines.append("")
    return "\n".join(lines)


def _build_delegate_tool_descriptions(targets: list[HandoffTarget]) -> str:
    """One-line-per-delegate descriptions for tool-style exposure."""
    if not targets:
        return ""
    parts = []
    for t in targets:
        desc = t.description or f"Delegate to {t.name}"
        parts.append(f"delegate_{t.name}: {desc}")
    return "\n".join(parts)


async def _check_filter(target: HandoffTarget, query: str) -> bool:
    """Run the target's filter_fn (sync or async). Returns True if eligible."""
    if target.filter_fn is None:
        return True
    result = target.filter_fn(query)
    if asyncio.iscoroutine(result):
        result = await result
    return bool(result)


async def _transform_query(target: HandoffTarget, query: str) -> str:
    """Apply the target's input_transform if set."""
    if target.input_transform is None:
        return query
    result = target.input_transform(query)
    if asyncio.iscoroutine(result):
        result = await result
    return str(result)


async def resolve_handoff(
    targets: list[HandoffTarget],
    query: str,
    delegate_name: str | None = None,
) -> HandoffTarget | None:
    """Match ``delegate_name`` if set, else first target passing ``filter_fn``."""
    if delegate_name:
        for t in targets:
            if t.name == delegate_name and await _check_filter(t, query):
                return t

    for t in targets:
        if await _check_filter(t, query):
            return t

    return None


async def run_delegate(
    target: HandoffTarget,
    query: str,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    lt_namespace: tuple | None = None,
    context: dict | None = None,
) -> ExecutionResult:
    """Run ``target.agent.ainvoke`` after optional ``input_transform``."""
    transformed = await _transform_query(target, query)

    logger.event(
        f"[Delegation] → {target.name}: {transformed[:80]!r}"
        + (f" (transformed from {query[:40]!r})" if transformed != query else "")
    )

    t0 = time.perf_counter()
    result = await target.agent.ainvoke(
        transformed,
        thread_id=thread_id,
        user_id=user_id,
        lt_namespace=lt_namespace,
        context=context,
    )
    dur_ms = round((time.perf_counter() - t0) * 1000, 1)

    logger.event(
        f"[Delegation] ← {target.name}: success={result.success} pattern={result.pattern_used.value} {dur_ms}ms"
    )
    return result


class BackgroundTaskStatus(str, Enum):
    """Status of a background delegation task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundTask:
    """Tracks a single background delegation."""

    task_id: str
    target_name: str
    query: str
    status: BackgroundTaskStatus = BackgroundTaskStatus.PENDING
    result: ExecutionResult | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    _async_task: asyncio.Task | None = field(default=None, repr=False)


class BackgroundDelegationManager:
    """Bookkeeping for ``adelegate_background`` (task ids, status, await/cancel)."""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self,
        target: HandoffTarget,
        query: str,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
    ) -> str:
        """Start delegation in a task; return ``task_id``."""
        task_id = str(uuid.uuid4())
        bg = BackgroundTask(
            task_id=task_id,
            target_name=target.name,
            query=query,
            status=BackgroundTaskStatus.RUNNING,
        )

        async def _run() -> None:
            try:
                result = await run_delegate(
                    target,
                    query,
                    thread_id=thread_id,
                    user_id=user_id,
                    lt_namespace=lt_namespace,
                    context=context,
                )
                bg.result = result
                bg.status = BackgroundTaskStatus.COMPLETED
            except asyncio.CancelledError:
                bg.status = BackgroundTaskStatus.CANCELLED
            except Exception as exc:
                bg.error = str(exc)
                bg.status = BackgroundTaskStatus.FAILED
                logger.warning(f"[BG-Delegation] task {task_id} failed: {exc!r}")
            finally:
                bg.completed_at = time.time()

        async with self._lock:
            async_task = asyncio.create_task(_run(), name=f"bg-delegate-{task_id[:8]}")
            bg._async_task = async_task
            self._tasks[task_id] = bg

        logger.event(f"[BG-Delegation] submitted task_id={task_id[:8]}… → {target.name}")
        return task_id

    def status(self, task_id: str) -> BackgroundTask | None:
        """Get current status of a background task. Returns None if not found."""
        return self._tasks.get(task_id)

    async def await_result(
        self,
        task_id: str,
        *,
        timeout: float | None = None,
    ) -> ExecutionResult | None:
        """Block until the task finishes; ``None`` if missing or no result."""
        bg = self._tasks.get(task_id)
        if bg is None:
            return None

        if bg._async_task is not None and not bg._async_task.done():
            await asyncio.wait_for(asyncio.shield(bg._async_task), timeout=timeout)

        return bg.result

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running task if possible."""
        bg = self._tasks.get(task_id)
        if bg is None:
            return False

        if bg._async_task is not None and not bg._async_task.done():
            bg._async_task.cancel()
            try:
                await bg._async_task
            except asyncio.CancelledError:
                pass
            bg.status = BackgroundTaskStatus.CANCELLED
            bg.completed_at = time.time()
            return True

        return False

    def list_tasks(self) -> list[BackgroundTask]:
        """Return all tracked background tasks (newest first)."""
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def cleanup(self, *, max_age_seconds: float = 3600) -> int:
        """Remove completed tasks older than max_age_seconds. Returns count removed."""
        cutoff = time.time() - max_age_seconds
        to_remove = [tid for tid, bg in self._tasks.items() if bg.completed_at is not None and bg.completed_at < cutoff]
        for tid in to_remove:
            del self._tasks[tid]
        return len(to_remove)


def make_agent_tool(
    agent: Any,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """Return a ``StructuredTool`` that calls ``agent.ainvoke``."""
    from langchain_core.tools import StructuredTool

    tool_name = name or f"ask_{agent.name}"
    tool_desc = description or (
        f"Delegate a task to the '{agent.name}' agent. Pass a natural language query and receive the agent's response."
    )

    async def _invoke(query: str) -> str:
        result = await agent.ainvoke(query)
        return result.output

    return StructuredTool.from_function(
        coroutine=_invoke,
        name=tool_name,
        description=tool_desc,
    )
