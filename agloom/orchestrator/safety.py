"""Recursion guards, cycle detection, timeout decay."""

from __future__ import annotations

import hashlib

from ..models import (
    OrchestrationContext,
    OrchestrationCycleDetected,
    PatternType,
    SpawnedPatternRecord,
)


def hash_task(task: str) -> str:
    normalized = " ".join((task or "").split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def check_cycle(ctx: OrchestrationContext, pattern: PatternType, task_hash: str) -> None:
    """Detect repeated (pattern, task) on the ancestor chain or rapid loops."""
    key = (pattern.value, task_hash)
    ancestors = [s for s in ctx.spawned_history if s.depth < ctx.current_depth]
    for record in ancestors:
        if (record.pattern.value, record.task_hash) == key:
            raise OrchestrationCycleDetected(
                f"Cycle detected: pattern={pattern.value} at depth={ctx.current_depth} "
                f"already executed at depth={record.depth} (spawn_id={record.spawn_id})"
            )
    recent = [s for s in ctx.spawned_history if s.depth >= ctx.current_depth - 2]
    if len(recent) >= 3:
        last_three = [(r.pattern.value, r.task_hash) for r in recent[-3:]]
        if len(set(last_three)) == 1:
            raise OrchestrationCycleDetected(
                f"Cycle detected: same pattern+task 3 times in last {len(recent)} spawns"
            )


def record_spawn(
    ctx: OrchestrationContext,
    *,
    spawn_id: str,
    pattern: PatternType,
    task_hash: str,
    worker_id: str,
    reason: str,
) -> None:
    ctx.spawned_history.append(
        SpawnedPatternRecord(
            spawn_id=spawn_id,
            pattern=pattern,
            task_hash=task_hash,
            worker_id=worker_id,
            parent_pattern=ctx.parent_pattern,
            reason=reason,
            depth=ctx.current_depth,
        )
    )


def apply_timeout(agent: dict, ctx: OrchestrationContext) -> float:
    """Diminishing per-depth LLM timeout (floor 15s)."""
    base = float(agent.get("llm_timeout", 120.0))
    decay = 0.8 ** ctx.current_depth
    return max(base * decay, 15.0)
