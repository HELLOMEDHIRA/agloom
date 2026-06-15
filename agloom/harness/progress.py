"""Cross-session task tracking: progress artifact, LTS-backed tracker, and agent-facing tools."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..logging_utils import get_logger

logger = get_logger(__name__)

_HARNESS_NS = ("harness", "progress")

_PROGRESS_FILE = "agloom-progress.json"


#  Enums & Models


class TaskStatus(str, Enum):
    """Lifecycle of a single task."""

    PENDING = "pending"  # Not yet started
    IN_PROGRESS = "in_progress"  # Currently being worked on
    PASSING = "passing"  # Verified — feature works end-to-end
    FAILING = "failing"  # Implemented but verification failed
    SKIPPED = "skipped"  # Intentionally skipped (out of scope)


class TaskPriority(str, Enum):
    """Task priority for ordering."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStep(BaseModel):
    """
    One verification step for a task.
    Mirrors Anthropic's feature list step structure.
    """

    description: str = Field(description="Human-readable description of this verification step")
    passes: bool = Field(default=False, description="Whether this step passed verification")
    notes: str = Field(default="", description="Optional notes from verification (error messages, etc.)")
    verified_at: str | None = Field(default=None, description="ISO timestamp when verified")


class Task(BaseModel):
    """
    A single unit of work in the progress artifact.

    Key rule from Anthropic's article:
      "Only mark passes=True after careful testing."
      We enforce this by requiring verification_steps to exist before
      marking a task PASSING.
    """

    id: str = Field(description="Unique task identifier (e.g. 'feat-001')")
    category: str = Field(description="Category label (e.g. 'functional', 'infra', 'testing')")
    description: str = Field(description="What this task does — human-readable")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Current lifecycle status")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Priority level")
    assigned_session: str | None = Field(default=None, description="Session ID that owns this task")
    verification_steps: list[TaskStep] = Field(
        default_factory=list,
        description="End-to-end verification steps. All must pass before status=PASSING.",
    )
    notes: str = Field(
        default="",
        description="Free-form notes: implementation details, blockers, next actions.",
    )
    error_summary: str = Field(
        default="",
        description="Last error encountered during verification, if any.",
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = Field(default=None, description="ISO timestamp when marked passing")
    attempt_count: int = Field(default=0, description="Number of times this task has been attempted")

    def mark_in_progress(self, session_id: str) -> None:
        """Claim this task for a session."""
        self.status = TaskStatus.IN_PROGRESS
        self.assigned_session = session_id
        self.attempt_count += 1
        self.updated_at = datetime.now(UTC).isoformat()

    def mark_passing(self) -> bool:
        """
        Mark task as passing. Returns True if all verification steps pass.
        Returns False and emits a warning if verification steps are missing or failing.
        """
        if not self.verification_steps:
            logger.warning(
                f"[Progress] Task {self.id}: cannot mark PASSING — "
                f"no verification_steps defined. Add verification steps first."
            )
            return False
        failing = [s for s in self.verification_steps if not s.passes]
        if failing:
            logger.warning(
                f"[Progress] Task {self.id}: cannot mark PASSING — "
                f"{len(failing)} verification step(s) still failing: "
                f"{[s.description for s in failing]}"
            )
            self.status = TaskStatus.FAILING
            self.error_summary = f"{len(failing)} steps failing: " + ", ".join(s.description for s in failing)
            self.updated_at = datetime.now(UTC).isoformat()
            return False

        self.status = TaskStatus.PASSING
        self.completed_at = datetime.now(UTC).isoformat()
        self.assigned_session = None
        self.updated_at = datetime.now(UTC).isoformat()
        return True

    def mark_failing(self, error: str = "") -> None:
        """Mark task as failing (implemented but verification failed)."""
        self.status = TaskStatus.FAILING
        self.error_summary = error
        self.updated_at = datetime.now(UTC).isoformat()

    def to_feature_dict(self) -> dict[str, Any]:
        """Export as Anthropic-style feature dict for classifier prompts."""
        return {
            "id": self.id,
            "category": self.category,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "verification_steps": [
                {
                    "description": s.description,
                    "passes": s.passes,
                    "notes": s.notes,
                }
                for s in self.verification_steps
            ],
        }


class ProgressArtifact(BaseModel):
    """
    The full progress manifest. Stored as a single artifact per project.

    This is the analogue of Anthropic's feature_list.json, but stored in
    LongTermStore instead of on disk — so it survives across sessions
    and is accessible to multiple agents.
    """

    project_name: str = Field(default="project", description="Human-readable project name")
    description: str = Field(
        default="",
        description="Overall project goal — set by initializer or first user query",
    )
    tasks: list[Task] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    total_sessions: int = Field(default=0, description="Number of sessions that have run")
    version: int = Field(default=1, description="Artifact schema version")

    @property
    def pending_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.PENDING]

    @property
    def in_progress_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.IN_PROGRESS]

    @property
    def passing_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.PASSING]

    @property
    def failing_tasks(self) -> list[Task]:
        return [t for t in self.tasks if t.status == TaskStatus.FAILING]

    @property
    def completion_ratio(self) -> float:
        if not self.tasks:
            return 0.0
        return len(self.passing_tasks) / len(self.tasks)

    def get_task(self, task_id: str) -> Task | None:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def get_next_task(self, session_id: str) -> Task | None:
        """
        Return the highest-priority pending task not owned by this session.
        Priority order: CRITICAL > HIGH > MEDIUM > LOW.
        Also returns in-progress tasks owned by this session (resume case).
        """
        candidates = self.pending_tasks + [t for t in self.in_progress_tasks if t.assigned_session == session_id]
        if not candidates:
            return None

        priority_order = [
            TaskPriority.CRITICAL,
            TaskPriority.HIGH,
            TaskPriority.MEDIUM,
            TaskPriority.LOW,
        ]
        candidates.sort(key=lambda t: (priority_order.index(t.priority), t.created_at))
        return candidates[0]

    def to_classifier_context(self) -> str:
        """
        Build a compact context block for the classifier prompt.
        Shows only pending + failing tasks so the agent knows what remains.
        """
        pending = self.pending_tasks
        failing = self.failing_tasks

        if not pending and not failing:
            if not self.tasks:
                goal = (self.description or "").strip()
                if goal:
                    return f"Harness: no tasks yet. Goal: {goal[:240]}"
                return "Harness: no tasks yet (call initialize_project to create tasks)."
            return (
                f"Progress: {len(self.passing_tasks)}/{len(self.tasks)} tasks complete. "
                "All tasks passing."
            )

        lines = [f"Progress: {len(self.passing_tasks)}/{len(self.tasks)} tasks complete."]
        if failing:
            lines.append(f"\n{len(failing)} task(s) FAILING (needs fixing):")
            for t in failing:
                lines.append(f"  [{t.id}] {t.description}")
                if t.error_summary:
                    lines.append(f"         Error: {t.error_summary[:120]}")

        if pending:
            lines.append(f"\n{len(pending)} task(s) PENDING:")
            for t in pending[:10]:
                lines.append(f"  [{t.id}] [{t.priority.value}] {t.description}")
            if len(pending) > 10:
                lines.append(f"  ... and {len(pending) - 10} more")

        return "\n".join(lines)

    def to_json_feature_list(self) -> str:
        """Export full feature list as JSON (Anthropic's format)."""
        return json.dumps(
            {
                "project": self.project_name,
                "description": self.description,
                "features": [t.to_feature_dict() for t in self.tasks],
                "completion": f"{len(self.passing_tasks)}/{len(self.tasks)}",
                "updated_at": self.updated_at,
            },
            indent=2,
        )


class BootstrapState(BaseModel):
    """
    Cross-session state written at the end of each session.
    Read at the start of the next session to understand project state.

    This mirrors Anthropic's "session warmup" steps:
      1. Run pwd to see directory
      2. Read git logs and progress notes
      3. Read features list
      4. Check for broken state
      5. Proceed
    """

    session_id: str = Field(description="Unique session identifier")
    session_number: int = Field(default=1, description="Sequential session count")
    last_task_id: str | None = Field(default=None, description="Last task worked on")
    last_task_status: TaskStatus | None = Field(default=None, description="Status of last task")
    clean_state: bool = Field(
        default=True,
        description="True if agent left environment in a clean (passing) state at session end",
    )
    blockers: list[str] = Field(
        default_factory=list,
        description="Known blockers that the next session should be aware of",
    )
    next_action: str = Field(
        default="",
        description="What the next session should do first",
    )
    git_commit_hash: str | None = Field(
        default=None,
        description="Last git commit SHA from this session (if git available)",
    )
    progress_snapshot: str = Field(
        default="",
        description="Short progress summary written by the agent at session end",
    )
    session_started_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    session_ended_at: str | None = Field(default=None)
    tools_available: list[str] = Field(
        default_factory=list,
        description="List of tool names available in this session",
    )
    error_summary: str | None = Field(
        default=None,
        description="Short error summary when clean_state is False (e.g. first blocker)",
    )

    def to_warmup_context(self) -> str:
        """Build the session warmup context block injected at the start of a new session."""
        lines = [
            f"Session #{self.session_number} — last session ended at {self.session_ended_at or 'unknown'}",
            "",
        ]
        if not self.clean_state:
            lines.append("⚠️  WARNING: Previous session left environment in a BROKEN state!")
            if self.last_task_id:
                st = self.last_task_status
                st_label = st.value if st is not None else "unknown"
                lines.append(f"   Last task: {self.last_task_id} ({st_label})")
            if self.error_summary:
                lines.append(f"   Error: {self.error_summary}")
            lines.append("")

        if self.progress_snapshot:
            lines.append(f"Last session summary:\n{self.progress_snapshot}")
            lines.append("")

        if self.blockers:
            lines.append("Known blockers:")
            for b in self.blockers:
                lines.append(f"  - {b}")
            lines.append("")

        if self.next_action:
            lines.append(f"Next action: {self.next_action}")

        return "\n".join(lines)


#  Progress Tracker


class ProgressTracker:
    """
    Manages the ProgressArtifact across sessions, backed by LongTermStore.

    Responsibilities:
      - Bootstrap the artifact on first run (from user goal or disk file)
      - Persist changes after each task update
      - Track BootstrapState per session
      - Provide tool functions for the agent to interact with progress
      - Generate feature list context for classifier prompts

    Thread-safety:
      Uses an asyncio.Lock to prevent concurrent writes from multiple agents.

    Usage:
        tracker = ProgressTracker(store, agent_name, project_name)

        # Agent calls at session start:
        artifact = await tracker.bootstrap(session_id)
        state = await tracker.get_bootstrap_state(session_id)
        next_task = artifact.get_next_task(session_id)

        # Agent calls during session:
        await tracker.update_task(task_id, status, notes)

        # Agent calls at session end:
        await tracker.write_bootstrap_state(session_id, clean_state=True, ...)
        await tracker.save_progress()
    """

    def __init__(
        self,
        store: Any,
        agent_name: str,
        project_name: str = "project",
    ) -> None:
        self._store = store
        self._agent_name = agent_name
        self._project_name = project_name
        self._artifact: ProgressArtifact | None = None
        self._lock = asyncio.Lock()
        self._session_states: dict[str, BootstrapState] = {}
        self._current_session: str | None = None
        self._bootstrapped_for_thread: str | None = None

    @property
    def artifact(self) -> ProgressArtifact:
        if self._artifact is None:
            self._artifact = ProgressArtifact(project_name=self._project_name)
        return self._artifact

    async def _lts_get(self, ns: tuple, key: str) -> Any | None:
        try:
            return await self._store.aget(ns, key)
        except Exception:
            return None

    async def _lts_save(
        self,
        ns: tuple,
        key: str,
        value: str,
        metadata: dict,
    ) -> None:
        await self._store.asave(namespace=ns, key=key, value=value, metadata=metadata)

    async def bootstrap(
        self,
        session_id: str,
        goal: str = "",
        from_disk: bool = True,
    ) -> ProgressArtifact:
        """
        Load or create the progress artifact for a new session.

        Priority:
          1. LongTermStore (survives across sessions, multi-agent shareable)
          2. Disk file (agloom-progress.json in cwd or parent dirs)
          3. Fresh artifact (first run — use goal as description)

        Also increments total_sessions counter.
        """
        async with self._lock:
            self._current_session = session_id

            existing = await self._lts_get(_HARNESS_NS, "artifact")
            if existing:
                try:
                    meta = getattr(existing, "value", {}) or {}
                    data = meta.get("artifact_json") or meta.get("memory") or meta.get("value", "{}")
                    if isinstance(data, str):
                        self._artifact = ProgressArtifact.model_validate_json(data)
                    else:
                        self._artifact = ProgressArtifact.model_validate(data)
                    logger.info(
                        f"[Progress] Loaded artifact from LTS: "
                        f"{len(self._artifact.tasks)} tasks, "
                        f"{self._artifact.completion_ratio:.0%} complete"
                    )
                except Exception as exc:
                    logger.warning(f"[Progress] Failed to load artifact from LTS ({exc!r}) — starting fresh")
                    self._artifact = ProgressArtifact(
                        project_name=self._project_name,
                        description=goal,
                    )
            elif from_disk:
                disk_artifact = self._load_from_disk()
                if disk_artifact:
                    self._artifact = disk_artifact
                    await self.save_progress()
                    logger.info(f"[Progress] Loaded artifact from disk: {len(self._artifact.tasks)} tasks")
                else:
                    self._artifact = ProgressArtifact(
                        project_name=self._project_name,
                        description=goal,
                    )
                    logger.info(f"[Progress] Created fresh artifact for goal: {goal[:80]!r}")
            else:
                self._artifact = ProgressArtifact(
                    project_name=self._project_name,
                    description=goal,
                )

            self._artifact.total_sessions += 1
            self._artifact.updated_at = datetime.now(UTC).isoformat()
            await self.save_progress()

            return self._artifact

    def _load_from_disk(self) -> ProgressArtifact | None:
        """Load ``agloom-progress.json`` from cwd only (no upward walk)."""
        try:
            f = Path.cwd() / _PROGRESS_FILE
        except Exception:
            f = Path(_PROGRESS_FILE)
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return ProgressArtifact.model_validate(data)
        except Exception as exc:
            logger.warning(f"[Progress] Failed to load {f}: {exc!r}")
            return None

    async def save_progress(self) -> None:
        """Persist current artifact to LongTermStore."""
        if self._artifact is None:
            return
        self._artifact.updated_at = datetime.now(UTC).isoformat()
        meta = {
            "project": self._project_name,
            "agent": self._agent_name,
            "updated_at": self._artifact.updated_at,
            "task_count": len(self._artifact.tasks),
            "passing_count": len(self._artifact.passing_tasks),
            "completion": f"{self._artifact.completion_ratio:.0%}",
        }
        await self._lts_save(
            _HARNESS_NS,
            "artifact",
            self._artifact.model_dump_json(),
            {**meta, "artifact_json": self._artifact.model_dump_json()},
        )

    async def write_to_disk(self, path: Path | None = None) -> str:
        """Write artifact to disk as agloom-progress.json. Returns the path."""
        async with self._lock:
            if self._artifact is None:
                raise ValueError("No artifact to write — call bootstrap() first")

            target = (path or Path.cwd()) / _PROGRESS_FILE
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = self._artifact.model_dump_json()
            tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                tmp.write_text(payload, encoding="utf-8")
                tmp.replace(target)
            except BaseException:
                if tmp.exists():
                    try:
                        tmp.unlink()
                    except OSError:
                        pass
                raise

        meta_file = target.with_suffix(".meta.json")
        meta_payload = json.dumps(
            {
                "project": self._project_name,
                "agent": self._agent_name,
                "saved_at": datetime.now(UTC).isoformat(),
                "completion": f"{self._artifact.completion_ratio:.0%}",
                "tasks": len(self._artifact.tasks),
                "version": self._artifact.version,
            },
            indent=2,
        )
        meta_tmp = meta_file.with_name(f"{meta_file.name}.{uuid.uuid4().hex}.tmp")
        try:
            meta_tmp.write_text(meta_payload, encoding="utf-8")
            meta_tmp.replace(meta_file)
        except BaseException:
            if meta_tmp.exists():
                try:
                    meta_tmp.unlink()
                except OSError:
                    pass
            raise
        logger.info(f"[Progress] Saved to disk: {target}")
        return str(target)

    async def add_task(
        self,
        task_id: str,
        description: str,
        category: str = "general",
        priority: TaskPriority = TaskPriority.MEDIUM,
        verification_steps: list[TaskStep] | None = None,
        notes: str = "",
    ) -> Task:
        """Add a new task to the artifact. Idempotent on task_id."""
        async with self._lock:
            existing = self.artifact.get_task(task_id)
            if existing:
                logger.debug(f"[Progress] Task {task_id} already exists — skipping add")
                return existing

            task = Task(
                id=task_id,
                category=category,
                description=description,
                priority=priority,
                verification_steps=verification_steps or [],
                notes=notes,
            )
            self.artifact.tasks.append(task)
            await self.save_progress()
            logger.info(f"[Progress] Added task: [{task_id}] {description[:60]}")
            return task

    async def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        notes: str | None = None,
        error: str | None = None,
        verification_steps: list[dict[str, Any]] | None = None,
    ) -> Task | None:
        """
        Update a task's status and/or notes.

        If status=PASSING is requested, validates that all verification_steps pass
        before marking. If verification_steps are provided, updates them first.
        """
        async with self._lock:
            task = self.artifact.get_task(task_id)
            if not task:
                logger.warning(f"[Progress] update_task: task {task_id} not found")
                return None

            if status is not None:
                if status == TaskStatus.PASSING:
                    if verification_steps:
                        for vs in verification_steps:
                            for existing in task.verification_steps:
                                if existing.description == vs.get("description", ""):
                                    existing.passes = vs.get("passes", False)
                                    existing.notes = vs.get("notes", "")
                                    if vs.get("passes"):
                                        existing.verified_at = datetime.now(UTC).isoformat()
                    task.mark_passing()
                elif status == TaskStatus.FAILING:
                    task.mark_failing(error or "")
                elif status == TaskStatus.IN_PROGRESS:
                    task.mark_in_progress(self._current_session or "")
                elif status == TaskStatus.SKIPPED:
                    task.status = TaskStatus.SKIPPED
                    task.assigned_session = None
                    task.updated_at = datetime.now(UTC).isoformat()
                else:
                    task.status = status

            if notes is not None:
                task.notes = notes

            await self.save_progress()
            return task

    async def claim_next_task(self, session_id: str) -> Task | None:
        """Atomically claim the highest-priority pending task for this session."""
        async with self._lock:
            task = self.artifact.get_next_task(session_id)
            if task:
                task.mark_in_progress(session_id)
                await self.save_progress()
                logger.info(f"[Progress] Session {session_id} claimed task: [{task.id}]")
            else:
                logger.info(f"[Progress] No pending tasks for session {session_id}")
            return task

    async def write_bootstrap_state(
        self,
        session_id: str,
        clean_state: bool = True,
        last_task_id: str | None = None,
        last_task_status: TaskStatus | None = None,
        blockers: list[str] | None = None,
        next_action: str = "",
        progress_snapshot: str = "",
        git_commit_hash: str | None = None,
        tools_available: list[str] | None = None,
        error_summary: str | None = None,
    ) -> BootstrapState:
        """Write the session end state for the next session to read."""
        async with self._lock:
            state = BootstrapState(
                session_id=session_id,
                session_number=self._artifact.total_sessions if self._artifact else 1,
                last_task_id=last_task_id,
                last_task_status=last_task_status,
                clean_state=clean_state,
                blockers=blockers or [],
                next_action=next_action,
                git_commit_hash=git_commit_hash,
                progress_snapshot=progress_snapshot,
                session_ended_at=datetime.now(UTC).isoformat(),
                tools_available=tools_available or [],
                error_summary=error_summary,
            )
            self._session_states[session_id] = state
            meta = state.model_dump()
            await self._lts_save(
                (*_HARNESS_NS, "sessions"),
                session_id,
                state.model_dump_json(),
                {**meta, "session_id": session_id},
            )
        logger.info(
            f"[Progress] Bootstrap state written: session={session_id} "
            f"clean={clean_state} blockers={len(blockers or [])}"
        )
        return state

    async def get_bootstrap_state(self, session_id: str) -> BootstrapState | None:
        """Load the last bootstrap state for a given session."""
        if session_id in self._session_states:
            return self._session_states[session_id]

        raw = await self._lts_get((*_HARNESS_NS, "sessions"), session_id)
        if not raw:
            return None
        try:
            meta = getattr(raw, "value", {}) or {}
            data = meta.get("memory") if isinstance(meta, dict) else None
            if not data:
                data = meta.get("value", "{}") if isinstance(meta, dict) else str(meta)
            if not isinstance(data, str) or data == "{}":
                data = meta.get("memory") or meta.get("value", "{}") if isinstance(meta, dict) else str(raw)
            state = BootstrapState.model_validate_json(data)
            self._session_states[session_id] = state
            return state
        except Exception as exc:
            logger.warning(f"[Progress] Failed to load bootstrap state for {session_id}: {exc!r}")
            return None

    async def get_last_session_state(self) -> BootstrapState | None:
        """Get the most recent session's bootstrap state."""
        if self._current_session and self._current_session in self._session_states:
            return self._session_states[self._current_session]
        return None

    def get_classifier_context(self) -> str:
        """Build the progress context block for classifier prompts."""
        if self._artifact is None:
            return ""
        return self._artifact.to_classifier_context()

    async def export_feature_list(self) -> str:
        """Export full feature list as Anthropic-format JSON string."""
        if self._artifact is None:
            return "{}"
        return self._artifact.to_json_feature_list()


#  Tool Functions (called by the agent)

_progress_trackers: dict[str, ProgressTracker] = {}
_tracker_lock = asyncio.Lock()


async def get_progress_tracker(
    store: Any,
    agent_name: str,
    project_name: str = "project",
) -> ProgressTracker:
    """Get or create a singleton ProgressTracker per (agent_name, project_name, event loop)."""
    key = f"{agent_name}:{project_name}"
    try:
        loop = asyncio.get_running_loop()
        key = f"{key}:loop:{id(loop)}"
    except RuntimeError:
        key = f"{key}:thread:{threading.get_ident()}"
    async with _tracker_lock:
        if key not in _progress_trackers:
            _progress_trackers[key] = ProgressTracker(store, agent_name, project_name)
        return _progress_trackers[key]


def save_progress_tool(tracker: ProgressTracker):
    """
    Factory: returns a tool function for the agent to save current progress.
    Usage: tool = save_progress_tool(tracker)
    """

    async def save_progress(
        notes: str = "",
        clean_state: bool = True,
    ) -> str:
        """
        Save current progress to the artifact. Call this at the end of
        significant work units and at session end.

        Args:
            notes: Free-form notes about what was accomplished.
            clean_state: True if the codebase is in a clean, working state.
                       Set False if you left bugs or incomplete work behind.
        """
        session_id = tracker._current_session or "unknown"
        task = await tracker.get_last_session_state()
        last_task_id = None
        last_status = None
        if task:
            last_task_id = task.last_task_id
            last_status = task.last_task_status

        in_progress = tracker.artifact.in_progress_tasks
        if in_progress:
            last_task_id = in_progress[0].id
            last_status = in_progress[0].status

        blockers = []
        failing = tracker.artifact.failing_tasks
        if not clean_state:
            blockers = [f"[{t.id}] {t.description}: {t.error_summary}" for t in failing]

        next_action = ""
        next_task = tracker.artifact.get_next_task(session_id)
        if next_task:
            next_action = f"Work on task [{next_task.id}]: {next_task.description}"

        await tracker.write_bootstrap_state(
            session_id=session_id,
            clean_state=clean_state,
            last_task_id=last_task_id,
            last_task_status=last_status,
            blockers=blockers,
            next_action=next_action,
            progress_snapshot=notes,
            error_summary=blockers[0] if blockers else None,
        )
        disk_path = await tracker.write_to_disk()
        return (
            f"Progress saved. {len(tracker.artifact.passing_tasks)}/{len(tracker.artifact.tasks)} "
            f"tasks passing. Clean state: {clean_state}. "
            f"Artifact written to: {disk_path}"
        )

    return save_progress


def update_task_tool(tracker: ProgressTracker):
    """
    Factory: returns a tool for the agent to update a specific task's status.
    """

    async def update_task(
        task_id: str,
        status: str,
        notes: str = "",
        error: str = "",
        verification_results: list[dict[str, Any]] | None = None,
    ) -> str:
        """
        Update a task's status and/or notes.

        Args:
            task_id: The task identifier (e.g. 'feat-001').
            status: One of: pending, in_progress, passing, failing, skipped.
            notes: Free-form notes (implementation details, next steps, etc.).
            error: Error message if status=failing.
            verification_results: List of step results.
                Example: [{{"description": "Click login button", "passes": true}}]
        """
        try:
            task_status = TaskStatus(status)
        except ValueError:
            return f"Invalid status: {status}. Must be one of: pending, in_progress, passing, failing, skipped."

        task = await tracker.update_task(
            task_id=task_id,
            status=task_status,
            notes=notes,
            error=error,
            verification_steps=verification_results,
        )
        if not task:
            return f"Task '{task_id}' not found in artifact."

        return (
            f"Task [{task_id}] updated: status={task.status.value}, completion={tracker.artifact.completion_ratio:.0%}"
        )

    return update_task


def get_next_task_tool(tracker: ProgressTracker):
    """
    Factory: returns a tool for the agent to claim the next pending task.
    """

    async def get_next_task() -> str:
        """
        Claim and return the highest-priority pending task for this session.

        Returns the task description, verification steps, and context.
        Call this at the start of a work session to know what to do next.
        """
        session_id = tracker._current_session or "unknown"
        task = await tracker.claim_next_task(session_id)

        if not task:
            completion = tracker.artifact.completion_ratio
            if completion >= 1.0:
                return f"All {len(tracker.artifact.tasks)} tasks complete! Project finished."
            return "No pending tasks found."

        steps_text = ""
        if task.verification_steps:
            steps_text = "\n\nVerification steps (ALL must pass before marking PASSING):\n"
            for i, s in enumerate(task.verification_steps, 1):
                check = "✅" if s.passes else "⬜"
                steps_text += f"  {check} {i}. {s.description}\n"

        return (
            f"Task: [{task.id}] — {task.description}\n"
            f"Category: {task.category} | Priority: {task.priority.value}\n"
            f"Attempt: #{task.attempt_count} | Last error: {task.error_summary or 'none'}\n"
            f"{steps_text}"
            f"\nNotes: {task.notes or 'none'}"
        )

    return get_next_task


def add_task_tool(tracker: ProgressTracker):
    """
    Factory: returns a tool for the agent to add a new task to the artifact.
    """

    async def add_task(
        task_id: str,
        description: str,
        category: str = "general",
        priority: str = "medium",
        verification_steps: list[dict[str, str]] | None = None,
    ) -> str:
        """
        Add a new task to the progress artifact.

        Args:
            task_id: Unique identifier (e.g. 'feat-001', 'infra-002').
            description: What this task does.
            category: Category label (e.g. 'functional', 'infra', 'testing').
            priority: One of: critical, high, medium, low.
            verification_steps: List of verification step descriptions.
                Example: ["Navigate to /login", "Enter credentials", "Click submit"]
        """
        try:
            pri = TaskPriority(priority)
        except ValueError:
            return f"Invalid priority: {priority}. Must be one of: critical, high, medium, low."

        steps = []
        if verification_steps:
            for desc in verification_steps:
                if isinstance(desc, dict):
                    steps.append(TaskStep(description=desc.get("description", "")))
                else:
                    steps.append(TaskStep(description=str(desc)))

        await tracker.add_task(
            task_id=task_id,
            description=description,
            category=category,
            priority=pri,
            verification_steps=steps,
        )
        return (
            f"Task [{task_id}] added. "
            f"Total tasks: {len(tracker.artifact.tasks)}, "
            f"pending: {len(tracker.artifact.pending_tasks)}"
        )

    return add_task


def bootstrap_progress_tool(tracker: ProgressTracker):
    """
    Factory: returns a tool for the agent to run the session bootstrap protocol.
    This is the first tool the agent should call at the start of every session.
    """

    async def bootstrap_progress(goal: str = "") -> str:
        """
        Run the session bootstrap protocol. Call this FIRST at the start of
        every session before doing any work.

        Steps:
          1. Get current session context (last session state, blockers)
          2. Review the full task list (pending, failing, passing)
          3. Select the highest-priority task to work on
          4. Return a structured briefing of what to do next

        Args:
            goal: Optional — update the project goal if it has changed.
        """
        session_id = tracker._current_session or "unknown"

        state = await tracker.get_bootstrap_state(session_id)
        warmup = state.to_warmup_context() if state else ""

        artifact = tracker.artifact
        progress_ctx = artifact.to_classifier_context()

        next_task = await tracker.claim_next_task(session_id)

        next_text = ""
        if next_task:
            next_text = (
                f"\n\nNEXT TASK:\n  [{next_task.id}] {next_task.description}\n  Priority: {next_task.priority.value}\n"
            )
            if next_task.verification_steps:
                next_text += "  Verification steps:\n"
                for i, s in enumerate(next_task.verification_steps, 1):
                    next_text += f"    {i}. {s.description}\n"

        return f"=== SESSION BOOTSTRAP ===\n\n{warmup}\n{progress_ctx}\n{next_text}\n=== END BOOTSTRAP ==="

    return bootstrap_progress


def cleanup_stale_progress_file(
    directory: Path | None = None,
    *,
    max_age_seconds: float = 7 * 24 * 3600,
) -> bool:
    """Remove ``agloom-progress.json`` when older than *max_age_seconds* (best-effort)."""
    base = directory or Path.cwd()
    target = base / _PROGRESS_FILE
    if not target.is_file():
        return False
    try:
        age = time.time() - target.stat().st_mtime
        if age < max_age_seconds:
            return False
        target.unlink()
        meta = target.with_suffix(".meta.json")
        if meta.is_file():
            meta.unlink()
        logger.info(f"ProgressTracker: removed stale {target.name} (age {age:.0f}s)")
        return True
    except OSError as exc:
        logger.debug(f"ProgressTracker: could not remove stale progress file: {exc!r}")
        return False
