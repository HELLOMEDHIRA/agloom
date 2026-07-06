"""Serialize harness planner + ledger state for AGP wire events."""

from __future__ import annotations

from typing import Any

from .events import HarnessLedgerTaskWire, HarnessPlanTaskWire


def harness_plan_tasks_wire(analysis: Any) -> list[HarnessPlanTaskWire]:
    """Turn planner ``harness_plan`` entries for ``pattern.classified`` / ``plan.preview``."""
    raw = getattr(analysis, "harness_plan", None) or []
    out: list[HarnessPlanTaskWire] = []
    for item in raw:
        if hasattr(item, "task_id"):
            out.append(
                HarnessPlanTaskWire(
                    task_id=str(item.task_id),
                    description=str(item.description),
                    category=str(getattr(item, "category", None) or "planned"),
                    priority=str(getattr(item, "priority", None) or "medium"),
                    verification_steps=[
                        str(s) for s in (getattr(item, "verification_steps", None) or []) if str(s).strip()
                    ],
                )
            )
        elif isinstance(item, dict):
            out.append(
                HarnessPlanTaskWire(
                    task_id=str(item.get("task_id", "")),
                    description=str(item.get("description", "")),
                    category=str(item.get("category", "planned")),
                    priority=str(item.get("priority", "medium")),
                    verification_steps=[
                        str(s) for s in (item.get("verification_steps") or []) if str(s).strip()
                    ],
                )
            )
    return out


def harness_work_kind_wire(analysis: Any) -> str | None:
    kind = (getattr(analysis, "harness_work_kind", None) or "").strip()
    return kind or None


def ledger_tasks_wire(tracker: Any) -> list[HarnessLedgerTaskWire]:
    """Current progress artifact tasks for ``harness.synced``."""
    artifact = getattr(tracker, "artifact", None)
    if artifact is None:
        return []
    tasks = getattr(artifact, "tasks", None) or []
    out: list[HarnessLedgerTaskWire] = []
    for task in tasks:
        status = getattr(task, "status", None)
        priority = getattr(task, "priority", None)
        out.append(
            HarnessLedgerTaskWire(
                task_id=str(getattr(task, "id", "")),
                description=str(getattr(task, "description", "")),
                category=str(getattr(task, "category", "planned")),
                status=status.value if hasattr(status, "value") else str(status or "pending"),
                priority=priority.value if hasattr(priority, "value") else str(priority or "medium"),
                verification_step_count=len(getattr(task, "verification_steps", None) or []),
            )
        )
    return out


def harness_sync_action(*, had_tasks: bool, tasks_synced: int) -> str:
    if tasks_synced <= 0:
        return "skip"
    return "append" if had_tasks else "seed"


def harness_plan_tasks_wire_from_wire(raw: Any) -> list[HarnessPlanTaskWire]:
    """Parse ``harness_plan`` from an in-process ``AgentEvent`` dict payload."""
    if not isinstance(raw, list):
        return []
    out: list[HarnessPlanTaskWire] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(
                HarnessPlanTaskWire(
                    task_id=str(item.get("task_id", "")),
                    description=str(item.get("description", "")),
                    category=str(item.get("category", "planned")),
                    priority=str(item.get("priority", "medium")),
                    verification_steps=[
                        str(s) for s in (item.get("verification_steps") or []) if str(s).strip()
                    ],
                )
            )
        elif hasattr(item, "task_id"):
            out.append(
                HarnessPlanTaskWire(
                    task_id=str(item.task_id),
                    description=str(item.description),
                    category=str(getattr(item, "category", None) or "planned"),
                    priority=str(getattr(item, "priority", None) or "medium"),
                    verification_steps=[
                        str(s) for s in (getattr(item, "verification_steps", None) or []) if str(s).strip()
                    ],
                )
            )
    return out


def ledger_tasks_wire_from_wire(raw: Any) -> list[HarnessLedgerTaskWire]:
    if not isinstance(raw, list):
        return []
    out: list[HarnessLedgerTaskWire] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            HarnessLedgerTaskWire(
                task_id=str(item.get("task_id", "")),
                description=str(item.get("description", "")),
                category=str(item.get("category", "planned")),
                status=str(item.get("status", "pending")),
                priority=str(item.get("priority", "medium")),
                verification_step_count=int(item.get("verification_step_count", 0) or 0),
            )
        )
    return out


__all__ = [
    "harness_plan_tasks_wire",
    "harness_plan_tasks_wire_from_wire",
    "harness_sync_action",
    "harness_work_kind_wire",
    "ledger_tasks_wire",
    "ledger_tasks_wire_from_wire",
]
