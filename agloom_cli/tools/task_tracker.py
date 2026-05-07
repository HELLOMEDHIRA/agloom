"""Task planning and tracking — break down complex tasks and track progress."""

from __future__ import annotations

import asyncio
from typing import Any

from ..tool_arg_coerce import absent_to_none, coerce_int
from ..tool_loader import tool

_task_tracker: dict[str, Any] = {}
_tracker_lock = asyncio.Lock()


@tool
async def create_task_plan(
    task: str,
    steps: list[str],
) -> str:
    """Create a task plan with discrete steps.

    Args:
        task: The main task description
        steps: List of steps to complete the task

    Returns:
        Task plan with ID and steps
    """
    import uuid

    task_id = uuid.uuid4().hex[:8]
    _task_tracker[task_id] = {
        "task": task,
        "steps": [{"id": i, "description": s, "status": "pending"} for i, s in enumerate(steps)],
        "current_step": 0,
        "completed": [],
    }

    result = [f"[Task ID: {task_id}]", f"Task: {task}", "", "Steps:"]
    for i, step in enumerate(steps):
        result.append(f"  {i + 1}. ⏳ {step}")

    return "\n".join(result)


@tool
async def get_current_task() -> str:
    """Get the current task status and progress.

    Returns:
        Current task info and progress
    """
    if not _task_tracker:
        return "No active tasks. Use create_task_plan first."

    active_tasks = [tid for tid, t in _task_tracker.items() if t["current_step"] < len(t["steps"])]

    if not active_tasks:
        return "All tasks completed!"

    tid = active_tasks[0]
    task = _task_tracker[tid]

    result = [
        f"[Task ID: {tid}]",
        f"Task: {task['task']}",
        "",
        "Progress:",
    ]

    for step in task["steps"]:
        idx = step["id"]
        desc = step["description"]
        status = step["status"]

        if status == "completed":
            result.append(f"  ✓ {idx + 1}. {desc}")
        elif idx == task["current_step"]:
            result.append(f"  → {idx + 1}. {desc} (in progress)")
        else:
            result.append(f"  ⏳ {idx + 1}. {desc}")

    total_steps = len(task["steps"])
    progress = (len(task["completed"]) / total_steps * 100) if total_steps > 0 else 0
    result.append(f"\nProgress: {len(task['completed'])}/{total_steps} ({progress:.0f}%)")

    return "\n".join(result)


@tool
async def complete_step(step_index: int | None = None) -> str:
    """Mark a step as complete and move to next.

    Args:
        step_index: Step number to complete (0-based). If None, completes current.

    Returns:
        Confirmation and next step info
    """
    if not _task_tracker:
        return "No active task. Use create_task_plan first."

    active_tasks = [tid for tid, t in _task_tracker.items() if t["current_step"] < len(t["steps"])]
    if not active_tasks:
        return "No active task to update."

    tid = active_tasks[0]
    task = _task_tracker[tid]

    if absent_to_none(step_index) is None:
        idx = task["current_step"]
    else:
        coerced, err = coerce_int(step_index, "step_index", min_value=0)
        if err:
            return err
        idx = coerced

    if idx < 0 or idx >= len(task["steps"]):
        return f"Invalid step index {idx}. Valid range: 0-{len(task['steps']) - 1}"

    task["steps"][idx]["status"] = "completed"
    if idx not in task["completed"]:
        task["completed"].append(idx)

    next_idx = idx + 1
    if next_idx < len(task["steps"]):
        task["current_step"] = next_idx
        next_step = task["steps"][next_idx]["description"]
        return f"✓ Step {idx + 1} completed. Next: {next_step}"
    return f"✓ Step {idx + 1} completed. All steps done!"


@tool
async def update_task_progress(
    current_step: int,
    total_steps: int,
    status: str = "in_progress",
) -> str:
    """Quick way to update task progress manually.

    Args:
        current_step: Current step number (0-based)
        total_steps: Total number of steps
        status: Status message

    Returns:
        Progress update confirmation
    """
    cur, err_a = coerce_int(current_step, "current_step", min_value=0)
    if err_a:
        return err_a
    tot, err_b = coerce_int(total_steps, "total_steps", min_value=1)
    if err_b:
        return err_b
    progress = (cur + 1) / tot * 100 if tot > 0 else 0
    return f"[{status}] Step {cur + 1}/{tot} ({progress:.0f}%)"


@tool
async def show_remaining_steps() -> str:
    """Show remaining steps in current task.

    Returns:
        List of remaining steps
    """
    if not _task_tracker:
        return "No active tasks."

    active_tasks = [tid for tid, t in _task_tracker.items() if t["current_step"] < len(t["steps"])]
    if not active_tasks:
        return "All tasks completed!"

    tid = active_tasks[0]
    task = _task_tracker[tid]

    remaining = task["steps"][task["current_step"] :]

    result = [f"Remaining steps for task {tid}:"]
    for step in remaining:
        result.append(f"  • {step['description']}")

    return "\n".join(result)


@tool
async def clear_task_tracker() -> str:
    """Clear all task tracking data.

    Returns:
        Confirmation
    """
    global _task_tracker
    _task_tracker = {}
    return "Task tracker cleared. Use create_task_plan to start new task."
