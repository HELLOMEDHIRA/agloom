"""Harness project contract: mandatory metadata when ``harness=True``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator



class HarnessMetadata(BaseModel):
    """
    Declares a durable harness **project** (scope + goal). Tasks may be empty at bind time;
    the turn planner populates them after the first ``plan_turn`` when ``needs_plan``.
    """

    project_name: str = Field(min_length=1, description="Artifact scope key (incident id, effort name, …)")
    goal: str = Field(min_length=1, description="North-star objective stored on the progress artifact")
    init_git: bool = Field(default=False, description="Run ``git init`` once when the cwd is not a repo")
    allow_replan: bool = Field(
        default=False,
        description="When True, later turns may append new ``harness_plan`` tasks to a non-empty artifact.",
    )
    force_plan: bool = Field(
        default=False,
        description="When True, skip length heuristics and allow harness seeding on shorter queries.",
    )
    tasks: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional pre-seeded tasks (integrator-owned). Skipped when the artifact already has tasks.",
    )

    @field_validator("project_name", "goal", mode="before")
    @classmethod
    def _strip_required_str(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


def runtime_default_harness_metadata(*, project_name: str = "agloom-runtime") -> HarnessMetadata:
    """Default project record for interactive ``agloom-runtime serve`` (no integrator metadata)."""
    return HarnessMetadata(
        project_name=project_name,
        goal="Interactive workspace session",
        init_git=False,
    )


def validate_harness_create_agent_kwargs(
    *,
    harness: bool,
    harness_metadata: HarnessMetadata | dict[str, Any] | None,
    store: Any,
    harness_available: bool,
) -> HarnessMetadata | None:
    """Validate ``create_agent`` harness arguments; return parsed metadata or ``None``."""
    if harness_metadata is not None and not harness:
        raise ValueError("harness_metadata requires harness=True")
    if not harness:
        return None
    if store is None:
        raise ValueError("harness=True requires store=")
    if not harness_available:
        raise ValueError("harness=True but harness dependencies are not available in this install")
    if harness_metadata is None:
        raise ValueError("harness=True requires harness_metadata=")
    if isinstance(harness_metadata, HarnessMetadata):
        return harness_metadata
    return HarnessMetadata.model_validate(harness_metadata)


HARNESS_TOOLS_APPENDIX = """

=== Harness progress tools ===
- Project scope and goal are fixed via ``harness_metadata`` at agent creation.
- The turn planner emits ``harness_plan`` on the first planning turn; use ``bootstrap_progress`` each session.
- During work: ``update_task``, ``save_progress``, ``get_next_task``.
"""


def format_harness_metadata_for_classifier(
    metadata: HarnessMetadata,
    *,
    needs_plan: bool,
    needs_replan: bool = False,
) -> str:
    """Compact harness project record for the turn planner prompt."""
    lines = [
        "=== HARNESS PROJECT ===",
        f"project_name: {metadata.project_name}",
        f"goal: {metadata.goal}",
        f"init_git: {str(metadata.init_git).lower()}",
        f"allow_replan: {str(metadata.allow_replan).lower()}",
        f"force_plan: {str(metadata.force_plan).lower()}",
    ]
    if metadata.tasks:
        lines.append(f"pre_seeded_tasks: {len(metadata.tasks)}")
    else:
        lines.append("pre_seeded_tasks: 0")
    if needs_plan:
        lines.append(
            "Planner: populate harness_plan + harness_work_kind when this turn needs durable "
            "multi-step work (see HARNESS RULE). Leave harness_plan empty for trivial turns."
        )
    elif needs_replan:
        lines.append(
            "Planner: append new harness_plan entries only for newly requested scope "
            "(see HARNESS RULE). Do not duplicate existing task ids."
        )
    else:
        lines.append(
            "Planner: harness ledger already has tasks — leave harness_plan empty."
        )
    return "\n".join(lines)


def build_harness_classifier_context(
    metadata: HarnessMetadata | None,
    progress_snippet: str,
    *,
    needs_plan: bool,
    needs_replan: bool = False,
) -> str:
    """Merge mandatory metadata with live artifact state for ``plan_turn``."""
    parts: list[str] = []
    if metadata is not None:
        parts.append(
            format_harness_metadata_for_classifier(
                metadata, needs_plan=needs_plan, needs_replan=needs_replan
            )
        )
    progress_snippet = (progress_snippet or "").strip()
    if progress_snippet:
        parts.append(progress_snippet)
    return "\n\n".join(parts)


async def apply_metadata_tasks(tracker: Any, tasks: list[dict[str, Any]]) -> int:
    """Seed tasks from integrator metadata when the artifact is still empty."""
    from .progress import TaskPriority, TaskStep

    if tracker.artifact.tasks:
        return len(tracker.artifact.tasks)

    allowed = {p.value for p in TaskPriority}
    created = 0
    for item in tasks:
        task_id = str(item.get("id", "")).strip()
        if not task_id:
            raise ValueError("each harness_metadata.tasks entry must include a non-empty 'id'")
        description = str(item.get("description", "")).strip() or task_id
        category = str(item.get("category", "planned"))
        raw_priority = item.get("priority", "medium")
        priority = TaskPriority(raw_priority) if raw_priority in allowed else TaskPriority.MEDIUM
        steps = []
        for step in item.get("verification_steps", []):
            if isinstance(step, dict):
                steps.append(TaskStep(description=str(step.get("description", ""))))
            elif isinstance(step, str):
                steps.append(TaskStep(description=step))
        await tracker.add_task(
            task_id=task_id,
            description=description,
            category=category,
            priority=priority,
            verification_steps=steps or [TaskStep(description=f"Verify: {description[:120]}")],
            notes=str(item.get("notes", "")),
        )
        created += 1
    if created:
        await tracker.save_progress()
    return created


async def bind_harness_project(
    tracker: Any,
    metadata: HarnessMetadata,
    *,
    session_id: str,
) -> None:
    """Load/create artifact, apply metadata goal/project, optional git + pre-seeded tasks."""
    await tracker.bootstrap(session_id, goal=metadata.goal)
    tracker.artifact.project_name = metadata.project_name
    if metadata.goal:
        tracker.artifact.description = metadata.goal
    if metadata.tasks:
        await apply_metadata_tasks(tracker, metadata.tasks)
    if metadata.init_git:
        from .git import GitSession

        git_session = GitSession()
        gs = await git_session.status()
        if not gs.is_repo:
            await git_session._run("init")
    await tracker.save_progress()
