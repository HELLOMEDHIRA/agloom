"""Harness turn planning: needs_plan, derive, sync, execution context."""

from __future__ import annotations

import re
from typing import Any

from ..src.models import HarnessPlanTask, PatternType, QueryAnalysis, SubTask

_TRIVIAL_USER_QUERY_RE = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|yo|sup)\s*[!?.]*\s*$",
    re.IGNORECASE,
)

_DURABLE_WORK_SIGNAL_RE = re.compile(
    r"""
    \b(investigat\w*|root\s*cause|rca|implement|build|fix|debug|deploy|refactor|
       incident|outage|feature|migrate|audit|analyze|analysis|multi[- ]step)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_REPLAN_SIGNAL_RE = re.compile(
    r"\b(add|append|new)\s+(tasks?|steps?|scope)|\b(expand|extend)\s+(the\s+)?(plan|scope)\b",
    re.IGNORECASE,
)


def _query_is_non_trivial(text: str, *, metadata: Any | None = None) -> bool:
    """Heuristic: user message may warrant durable harness work."""
    if not text:
        return False
    if getattr(metadata, "force_plan", False):
        return True
    if _TRIVIAL_USER_QUERY_RE.match(text):
        return False
    if len(text) < 24 and not _DURABLE_WORK_SIGNAL_RE.search(text):
        return False
    return True


def needs_harness_plan(
    tracker: Any | None,
    *,
    harness_enabled: bool,
    user_query: str,
    metadata: Any | None = None,
) -> bool:
    """True when the turn planner should seed an empty harness ledger."""
    if not harness_enabled:
        return False
    if tracker is not None and tracker.artifact.tasks:
        return False
    return _query_is_non_trivial((user_query or "").strip(), metadata=metadata)


def needs_harness_replan(
    tracker: Any | None,
    *,
    harness_enabled: bool,
    user_query: str,
    allow_replan: bool,
) -> bool:
    """True when ``allow_replan`` and the user may be requesting new harness tasks."""
    if not harness_enabled or not allow_replan:
        return False
    if tracker is None or not tracker.artifact.tasks:
        return False
    text = (user_query or "").strip()
    if not text or _TRIVIAL_USER_QUERY_RE.match(text):
        return False
    if _REPLAN_SIGNAL_RE.search(text):
        return True
    return len(text) >= 24 or _DURABLE_WORK_SIGNAL_RE.search(text) is not None


def classifier_harness_wire_enabled(
    tracker: Any | None,
    *,
    harness_enabled: bool,
    user_query: str,
    metadata: Any | None = None,
) -> bool:
    """Include harness wire fields + HARNESS RULE when seeding or replanning."""
    if not harness_enabled:
        return False
    allow_replan = bool(getattr(metadata, "allow_replan", False))
    if needs_harness_plan(
        tracker, harness_enabled=True, user_query=user_query, metadata=metadata
    ):
        return True
    return needs_harness_replan(
        tracker,
        harness_enabled=True,
        user_query=user_query,
        allow_replan=allow_replan,
    )


def harness_plan_from_subtasks(subtasks: list[SubTask]) -> list[HarnessPlanTask]:
    """Map pattern ``subtasks`` → durable harness plan entries."""
    total = len(subtasks)
    plans: list[HarnessPlanTask] = []
    for index, subtask in enumerate(subtasks):
        task_id = (subtask.worker_id or f"step-{index + 1}").strip()
        description = (subtask.task or task_id).strip()
        priority = _priority_for_index(index, total)
        verify = f"Complete: {description[:160]}"
        category = "planned"
        if subtask.context.get("harness_category"):
            category = subtask.context["harness_category"]
        plans.append(
            HarnessPlanTask(
                task_id=task_id,
                description=description,
                category=category,
                priority=priority,
                verification_steps=[verify],
            )
        )
    return plans


def merge_harness_plan_from_subtasks(analysis: QueryAnalysis) -> QueryAnalysis:
    """Fill ``harness_plan`` from ``subtasks`` when the model omitted harness fields."""
    if analysis.harness_plan or not analysis.subtasks:
        return analysis
    return analysis.model_copy(
        update={"harness_plan": harness_plan_from_subtasks(analysis.subtasks)},
    )


async def apply_work_kind_from_analysis(tracker: Any, analysis: QueryAnalysis) -> None:
    """Update artifact ``work_kind`` when the planner sends a non-empty label."""
    kind = (analysis.harness_work_kind or "").strip()
    if not kind:
        return
    await tracker.set_work_kind(kind)


def _priority_and_steps(item: HarnessPlanTask) -> tuple[Any, list[Any]]:
    from .progress import TaskPriority, TaskStep

    allowed = {p.value for p in TaskPriority}
    priority = TaskPriority(item.priority) if item.priority in allowed else TaskPriority.MEDIUM
    steps = [TaskStep(description=s) for s in item.verification_steps if s.strip()]
    if not steps:
        steps = [TaskStep(description=f"Verify: {item.description[:160]}")]
    return priority, steps


async def _add_plan_item(tracker: Any, item: HarnessPlanTask) -> None:
    priority, steps = _priority_and_steps(item)
    await tracker.add_task(
        task_id=item.task_id,
        description=item.description,
        category=item.category or "planned",
        priority=priority,
        verification_steps=steps,
    )


async def append_harness_plan(tracker: Any, plan: list[HarnessPlanTask]) -> int:
    """Add harness tasks by id (skip duplicates). Used when ``allow_replan`` is set."""
    if not plan:
        return 0
    added = 0
    for item in plan:
        if tracker.artifact.get_task(item.task_id):
            continue
        await _add_plan_item(tracker, item)
        added += 1
    if added:
        await tracker.save_progress()
    return added


async def _persist_harness_plan(tracker: Any, plan: list[HarnessPlanTask], analysis: QueryAnalysis) -> int:
    for item in plan:
        await _add_plan_item(tracker, item)
    if not tracker.artifact.work_kind:
        tracker.artifact.work_kind = (
            (analysis.harness_work_kind or "").strip() or analysis.pattern.value
        )
    await tracker.save_progress()
    return len(plan)


async def _persist_from_subtasks(tracker: Any, analysis: QueryAnalysis) -> int:
    from .progress import TaskPriority, TaskStep

    total = len(analysis.subtasks)
    allowed = {p.value for p in TaskPriority}
    for index, subtask in enumerate(analysis.subtasks):
        task_id = (subtask.worker_id or f"step-{index + 1}").strip()
        description = (subtask.task or task_id).strip()
        priority_label = _priority_for_index(index, total)
        priority = (
            TaskPriority(priority_label) if priority_label in allowed else TaskPriority.MEDIUM
        )
        verify = f"Complete: {description[:160]}"
        await tracker.add_task(
            task_id=task_id,
            description=description,
            category="planned",
            priority=priority,
            verification_steps=[TaskStep(description=verify)],
            notes=subtask.system_instruction[:500] if subtask.system_instruction else "",
        )
    if not tracker.artifact.work_kind:
        tracker.artifact.work_kind = analysis.pattern.value
    await tracker.save_progress()
    return total


async def sync_harness_from_analysis(
    tracker: Any,
    analysis: QueryAnalysis,
    *,
    allow_replan: bool = False,
) -> int:
    """
    Persist planner harness output. Seeds empty artifacts; appends when ``allow_replan``.
    """
    analysis = merge_harness_plan_from_subtasks(analysis)
    await apply_work_kind_from_analysis(tracker, analysis)

    if tracker.artifact.tasks:
        if not allow_replan:
            if analysis.harness_work_kind:
                await tracker.save_progress()
            return 0
        if analysis.harness_plan:
            return await append_harness_plan(tracker, analysis.harness_plan)
        return 0

    if analysis.harness_plan:
        return await _persist_harness_plan(tracker, analysis.harness_plan, analysis)

    if analysis.subtasks:
        return await _persist_from_subtasks(tracker, analysis)

    if analysis.harness_work_kind:
        await tracker.save_progress()
    return 0


def build_harness_execution_context(tracker: Any | None) -> str:
    """Current harness focus block for pattern handlers and workers."""
    if tracker is None:
        return ""
    artifact = getattr(tracker, "artifact", None)
    if artifact is None or not artifact.tasks:
        return ""
    session = getattr(tracker, "_current_session", None) or "session"
    nxt = artifact.get_next_task(session)
    lines = [
        "=== HARNESS CURRENT FOCUS ===",
        f"project: {artifact.project_name}",
        f"progress: {len(artifact.passing_tasks)}/{len(artifact.tasks)} tasks complete",
    ]
    if artifact.work_kind:
        lines.append(f"work_kind: {artifact.work_kind}")
    if nxt:
        lines.append(f"active_task: [{nxt.id}] {nxt.description}")
        if nxt.verification_steps:
            lines.append("verification:")
            for step in nxt.verification_steps[:5]:
                lines.append(f"  - {step.description}")
    elif artifact.pending_tasks:
        t = artifact.pending_tasks[0]
        lines.append(f"suggested_next: [{t.id}] {t.description}")
    return "\n".join(lines)


def _priority_for_index(index: int, total: int) -> str:
    if index == 0:
        return "critical"
    if index < max(2, total // 2):
        return "high"
    return "medium"
