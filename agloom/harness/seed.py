"""Programmatic harness task seeding (integrators, tests, incident workflows)."""

from __future__ import annotations

from typing import Any

from .progress import Task, TaskPriority, TaskStep, get_progress_tracker


async def seed_harness_tasks(
    store: Any,
    agent_name: str,
    project_name: str,
    tasks: list[Task | dict[str, Any]],
    *,
    goal: str = "",
    session_id: str = "seed",
    replace: bool = False,
) -> int:
    """
    Pre-populate the harness artifact with tasks before the agent's first turn.

    Idempotent by default: when tasks already exist and ``replace=False``, returns
    the existing task count without adding duplicates.

    Returns:
        Number of tasks in the artifact after seeding.
    """
    tracker = await get_progress_tracker(store, agent_name, project_name)
    await tracker.bootstrap(session_id, goal=goal)

    if tracker.artifact.tasks and not replace:
        return len(tracker.artifact.tasks)

    if replace:
        tracker.artifact.tasks = []

    allowed_priorities = {p.value for p in TaskPriority}
    for item in tasks:
        if isinstance(item, Task):
            task_id = item.id
            description = item.description
            category = item.category
            priority = item.priority
            steps = list(item.verification_steps)
            notes = item.notes
        else:
            task_id = str(item.get("id", ""))
            if not task_id:
                raise ValueError("each task dict must include an 'id' key")
            description = str(item.get("description", ""))
            category = str(item.get("category", "general"))
            raw_priority = item.get("priority", "medium")
            priority = (
                TaskPriority(raw_priority)
                if raw_priority in allowed_priorities
                else TaskPriority.MEDIUM
            )
            steps = []
            for step in item.get("verification_steps", []):
                if isinstance(step, TaskStep):
                    steps.append(step)
                elif isinstance(step, dict):
                    steps.append(TaskStep(description=str(step.get("description", ""))))
                elif isinstance(step, str):
                    steps.append(TaskStep(description=step))
            notes = str(item.get("notes", ""))

        await tracker.add_task(
            task_id=task_id,
            description=description,
            category=category,
            priority=priority,
            verification_steps=steps,
            notes=notes,
        )

    if goal and not tracker.artifact.description:
        tracker.artifact.description = goal

    await tracker.save_progress()
    return len(tracker.artifact.tasks)
