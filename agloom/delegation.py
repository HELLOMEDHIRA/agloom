# delegation.py
# ─────────────────────────────────────────────────────────────────────────────
# Task Delegation System for agloom.
#
# Four delegation patterns, all composable:
#
#   1. as_tool()              — expose an agent as a LangChain tool
#   2. register_handoff()     — transparent classifier-driven hand-off
#   3. delegates=[]           — hierarchical delegation via run_delegate()
#   4. adelegate_background() — fire-and-forget background delegation
#
# Design decisions:
#
#   - HandoffTarget is the universal descriptor for a delegate agent.
#     It holds the agent, a name/description for routing, and optional
#     filter functions for conditional hand-off.
#
#   - _build_delegation_context() assembles a description block injected
#     into the classifier prompt so the LLM can pick the right delegate.
#
#   - Background tasks use asyncio.Task with a tracking dict on the parent
#     config. Status/cancel/await are first-class operations.
#
#   - All delegation is async-first; the sync invoke() wrapper on
#     UnifiedAgent handles the bridge.
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
#  HandoffTarget — universal delegate descriptor
# ─────────────────────────────────────────────────────────────────────────────


class HandoffTarget:
    """
    Describes a delegate agent that can receive work from a parent.

    Parameters
    ----------
    agent : UnifiedAgent
        The delegate agent instance.
    name : str | None
        Display name for routing/logging. Defaults to agent.name.
    description : str
        What this delegate specialises in. Injected into the classifier
        prompt so the LLM knows when to route here.
    filter_fn : Callable[[str], bool] | None
        Optional sync/async predicate. When set, hand-off only occurs
        if filter_fn(query) returns True. None = always eligible.
    input_transform : Callable[[str], str] | None
        Optional query transform before delegation. Useful for
        stripping prefixes or reformatting.
    """

    __slots__ = ("agent", "description", "filter_fn", "input_transform", "name")

    def __init__(
        self,
        agent: Any,  # UnifiedAgent — Any to avoid circular import
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


# ─────────────────────────────────────────────────────────────────────────────
#  Delegation Context Builder
# ─────────────────────────────────────────────────────────────────────────────


def _build_delegation_context(targets: list[HandoffTarget]) -> str:
    """
    Build a text block describing available delegates for injection
    into the classifier prompt.

    Format:
      AVAILABLE DELEGATES
      ═══════════════════
        - [research_agent] Research and summarize academic papers
        - [code_agent] Write, review, and debug code

    The classifier uses this to decide whether to route to a delegate
    (via HANDOFF pattern) instead of handling locally.
    """
    if not targets:
        return ""

    lines = ["AVAILABLE DELEGATES", "=" * 55, ""]
    for t in targets:
        desc = t.description or f"Delegate agent: {t.name}"
        lines.append(f"  - [{t.name}] {desc}")
    lines.append("")
    return "\n".join(lines)


def _build_delegate_tool_descriptions(targets: list[HandoffTarget]) -> str:
    """
    Build tool-style descriptions for delegates, used when delegates
    are exposed as callable tools to the parent agent.
    """
    if not targets:
        return ""
    parts = []
    for t in targets:
        desc = t.description or f"Delegate to {t.name}"
        parts.append(f"delegate_{t.name}: {desc}")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
#  Handoff Resolution
# ─────────────────────────────────────────────────────────────────────────────


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
    """
    Find the best HandoffTarget for a query.

    Priority:
      1. If delegate_name is specified (from classifier), match by name.
      2. Otherwise, return the first target whose filter_fn passes.

    Returns None if no target matches.
    """
    if delegate_name:
        for t in targets:
            if t.name == delegate_name and await _check_filter(t, query):
                return t

    # Fallback: first eligible target
    for t in targets:
        if await _check_filter(t, query):
            return t

    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Delegate Execution
# ─────────────────────────────────────────────────────────────────────────────


async def run_delegate(
    target: HandoffTarget,
    query: str,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    lt_namespace: tuple | None = None,
    context: dict | None = None,
) -> ExecutionResult:
    """
    Execute a query on a delegate agent.

    Applies input_transform if set, then calls delegate.ainvoke().
    The result is returned as-is — the parent can wrap/transform it.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
#  Background Delegation
# ─────────────────────────────────────────────────────────────────────────────


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
    """
    Manages fire-and-forget background delegations on a parent agent.

    Stored on the parent config as config["_bg_delegation_manager"].
    Each background task gets a UUID and is tracked in self._tasks.
    """

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
        """
        Submit a background delegation. Returns task_id immediately.

        The delegation runs as an asyncio.Task. Use status(), await_result(),
        or cancel() to manage it.
        """
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
        """
        Wait for a background task to complete and return its result.

        Returns None if task_id not found or task failed/cancelled.
        Raises asyncio.TimeoutError if timeout expires.
        """
        bg = self._tasks.get(task_id)
        if bg is None:
            return None

        if bg._async_task is not None and not bg._async_task.done():
            await asyncio.wait_for(asyncio.shield(bg._async_task), timeout=timeout)

        return bg.result

    async def cancel(self, task_id: str) -> bool:
        """
        Cancel a running background task.

        Returns True if the task was cancelled, False if not found or already done.
        """
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


# ─────────────────────────────────────────────────────────────────────────────
#  Tool Factory — as_tool()
# ─────────────────────────────────────────────────────────────────────────────


def make_agent_tool(
    agent: Any,  # UnifiedAgent
    *,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """
    Wrap a UnifiedAgent as a LangChain StructuredTool.

    The resulting tool can be added to another agent's tool list,
    enabling tool-call-based delegation.

    Parameters
    ----------
    agent : UnifiedAgent
        The agent to wrap.
    name : str | None
        Tool name. Defaults to f"ask_{agent.name}".
    description : str | None
        Tool description. Defaults to a generic delegation description.
    """
    from langchain_core.tools import StructuredTool

    tool_name = name or f"ask_{agent.name}"
    tool_desc = description or (
        f"Delegate a task to the '{agent.name}' agent. Pass a natural language query and receive the agent's response."
    )

    async def _invoke(query: str) -> str:
        """Invoke the delegate agent with a query."""
        result = await agent.ainvoke(query)
        return result.output

    return StructuredTool.from_function(
        coroutine=_invoke,
        name=tool_name,
        description=tool_desc,
    )
