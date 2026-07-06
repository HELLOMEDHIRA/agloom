"""First-run setup: manual task decomposition via ``initialize_project`` (escape hatch)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..src.logging_utils import get_logger
from .progress import (
    TaskPriority,
    TaskStep,
    get_progress_tracker,
)

logger = get_logger(__name__)

_DECOMPOSE_PROMPT = """\
Decompose the following goal into a structured list of concrete, verifiable tasks.

Rules:
  - Every task MUST have end-to-end verification steps.
  - Order tasks logically for the goal (foundation first when applicable).
  - Category labels: functional, infra, testing, context, evidence, validation, report, general
  - Priority: critical, high, medium, low

Goal:
{goal}

Return a structured list of tasks.
"""


class TaskDecompositionToolPayload(BaseModel):
    """Structured output for task decomposition."""

    tasks: list[dict] = Field(
        description=(
            "List of tasks. Each task must have: id, category, description, "
            "priority (critical/high/medium/low), and verification_steps (list of step descriptions)."
        )
    )
    project_description: str = Field(description="Refined, expanded project description from the user's goal.")
    estimated_sessions: int = Field(description="Estimated number of sessions needed to complete all tasks.")


class InitializerResult(BaseModel):
    """Result of running the initializer."""

    briefing: str = Field(description="Human-readable briefing for the first coding agent.")
    tasks_created: int = Field(description="Number of tasks added to the progress artifact.")
    first_task: str | None = Field(description="Task ID of the recommended first task.")
    git_init: bool = Field(description="Whether git was initialized.")
    project_description: str = Field(description="The expanded project description.")


async def run_initializer(
    llm: Any,
    store: Any,
    agent_name: str,
    project_name: str,
    goal: str,
    *,
    max_tasks: int = 50,
    llm_timeout: float = 60.0,
    init_git: bool = False,
    git_initial_snapshot: bool = False,
) -> InitializerResult:
    """
    Manual harness seeding via ``initialize_project`` tool only.

    Normal flows use classifier subtasks + ``sync_harness_from_analysis`` — not this LLM call.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    tracker = await get_progress_tracker(store, agent_name, project_name)
    await tracker.bootstrap("init", goal=goal)

    already_initialized = tracker.artifact.tasks and tracker.artifact.total_sessions > 0
    if already_initialized:
        logger.info(
            f"[Initializer] Project '{project_name}' already initialized: {len(tracker.artifact.tasks)} tasks exist."
        )
        next_t = tracker.artifact.get_next_task(tracker._current_session or "init")
        return InitializerResult(
            briefing=(
                f"Project already initialized with {len(tracker.artifact.tasks)} tasks.\n"
                f"Run bootstrap_progress to begin."
            ),
            tasks_created=len(tracker.artifact.tasks),
            first_task=next_t.id if next_t else None,
            git_init=False,
            project_description=tracker.artifact.description,
        )

    prompt = _DECOMPOSE_PROMPT.format(goal=goal)

    from ..src.llm_utils import robust_structured_call

    try:
        raw = await robust_structured_call(
            llm,
            TaskDecompositionToolPayload,
            [
                SystemMessage(
                    content="You are a project planner. Decompose the goal into verifiable tasks."
                ),
                HumanMessage(content=prompt),
            ],
            max_retries=2,
            timeout=llm_timeout,
            caller="initializer",
        )
    except Exception as exc:
        logger.warning(f"[Initializer] Task decomposition LLM call failed ({exc!r})")
        raw = None

    tasks_created = 0
    briefing_lines = [
        f"=== INITIALIZATION COMPLETE — {project_name} ===",
        "",
        f"Goal: {goal[:200]}",
        "",
    ]

    if raw and hasattr(raw, "tasks") and raw.tasks:
        allowed_priorities = {p.value for p in TaskPriority}
        for task_dict in raw.tasks[:max_tasks]:
            task_id = task_dict.get("id", f"task-{tasks_created + 1}")
            category = task_dict.get("category", "general")
            description = task_dict.get("description", "")
            priority = task_dict.get("priority", "medium")
            step_dicts = task_dict.get("verification_steps", [])

            steps = []
            for step in step_dicts:
                if isinstance(step, dict):
                    steps.append(TaskStep(description=step.get("description", "")))
                elif isinstance(step, str):
                    steps.append(TaskStep(description=step))

            await tracker.add_task(
                task_id=task_id,
                description=description,
                category=category,
                priority=TaskPriority(priority) if priority in allowed_priorities else TaskPriority.MEDIUM,
                verification_steps=steps,
            )
            tasks_created += 1

        tracker.artifact.description = getattr(raw, "project_description", goal)
        briefing_lines.append(f"Generated {tasks_created} task(s) from goal decomposition.")
        briefing_lines.append(f"Estimated sessions: {getattr(raw, 'estimated_sessions', 'unknown')}")
    else:
        await tracker.add_task(
            task_id="task-001",
            description=goal,
            category="general",
            priority=TaskPriority.CRITICAL,
            verification_steps=[
                TaskStep(description="Verify the core goal is achieved end-to-end"),
            ],
        )
        tasks_created = 1
        briefing_lines.append(
            "Task decomposition failed — created single fallback task. "
            "Use add_task to create more tasks as work progresses."
        )

    await tracker.save_progress()

    briefing_lines.append("")
    briefing_lines.append("Task summary:")
    for t in tracker.artifact.tasks[:15]:
        briefing_lines.append(f"  [{t.id}] [{t.priority.value}] {t.description[:70]}")
    if len(tracker.artifact.tasks) > 15:
        briefing_lines.append(f"  ... and {len(tracker.artifact.tasks) - 15} more")
    briefing_lines.append("")
    briefing_lines.append("Run bootstrap_progress to begin working.")

    first_task = tracker.artifact.get_next_task(tracker._current_session or "init")
    git_init = False

    if init_git:
        from .git import GitSession

        git_session = GitSession()
        gs = await git_session.status()
        if not gs.is_repo:
            rc, _, _ = await git_session._run("init")
            if rc == 0:
                git_init = True
                if git_initial_snapshot:
                    rc2, _, _ = await git_session._run("add", "-A", "--", ".")
                    if rc2 == 0:
                        await git_session.commit(
                            f"feat: initial project setup — {project_name}",
                        )
                briefing_lines.append(
                    "Git repository initialized"
                    + (" with initial commit." if git_initial_snapshot else " (no files committed yet).")
                )

    briefing = "\n".join(briefing_lines)
    logger.info(f"[Initializer] Complete: {tasks_created} tasks, git={git_init}, project={project_name!r}")

    return InitializerResult(
        briefing=briefing,
        tasks_created=tasks_created,
        first_task=first_task.id if first_task else None,
        git_init=git_init,
        project_description=tracker.artifact.description,
    )


def create_initializer_tool(
    llm: Any,
    store: Any,
    agent_name: str,
    project_name: str,
    *,
    default_init_git: bool = False,
):
    """Factory: returns ``initialize_project`` — manual recovery only; classifier owns normal planning."""

    async def initialize_project(
        goal: str,
        init_git: bool | None = None,
        git_initial_snapshot: bool = False,
    ) -> str:
        """
        Manually decompose a goal into harness tasks. Prefer classifier subtasks in normal flows.

        Args:
            goal: The overall project goal.
            init_git: Whether to initialize a git repository (default from harness_metadata).
            git_initial_snapshot: Stage and commit all files after ``git init`` (default: False).
        """
        result = await run_initializer(
            llm=llm,
            store=store,
            agent_name=agent_name,
            project_name=project_name,
            goal=goal,
            init_git=default_init_git if init_git is None else init_git,
            git_initial_snapshot=git_initial_snapshot,
        )
        return result.briefing

    return initialize_project
