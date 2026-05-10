"""AGP inbound command models — typed counterparts to the event models.

Every command the frontend sends to the runtime uses the same envelope-style
JSON structure as events.  This module defines Pydantic models for all known
commands so the serve loop can validate and dispatch with full type safety
instead of raw ``dict.get()`` calls.

Wire format (same NDJSON stream as events, direction reversed)::

    {"type": "command.invoke",         "data": {"prompt": "Read pyproject.toml", "thread": "t_abc"}}
    {"type": "command.cancel",          "data": {"thread": "t_abc"}}
    {"type": "command.hitl.respond",    "data": {"request_id": "hr_…", "decision": "accept"}}
    {"type": "command.runtime.shutdown","data": {}}
    {"type": "command.worker.assign",   "data": {"worker_id": "w_1", "task": "…", "thread": "t_w"}}

Parse any inbound line with :data:`command_adapter`::

    cmd = command_adapter.validate_python(json.loads(line))
    if isinstance(cmd, CommandInvoke):
        ...
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class _CmdBase(BaseModel):
    model_config = ConfigDict(extra="allow")  # forward-compatible: tolerate unknown fields


# ── command.invoke ─────────────────────────────────────────────────────────────


class CommandInvokeData(_CmdBase):
    """Start a new agent turn. ``thread`` is optional — the runtime mints one when absent."""

    prompt: str
    thread: str | None = None
    user_id: str | None = None
    context: dict[str, Any] | None = None


class CommandInvoke(_CmdBase):
    type: Literal["command.invoke"] = "command.invoke"
    data: CommandInvokeData


# ── command.cancel ─────────────────────────────────────────────────────────────


class CommandCancelData(_CmdBase):
    """Cancel one (or all) in-flight invocations.

    When ``thread`` is supplied, only the matching invocation is cancelled.
    When absent, all running invocations on this session are cancelled.
    Cancellation produces ``session.closed(reason="user_aborted")`` on the wire.
    """

    thread: str | None = None


class CommandCancel(_CmdBase):
    type: Literal["command.cancel"] = "command.cancel"
    data: CommandCancelData = Field(default_factory=CommandCancelData)


# ── command.hitl.respond ───────────────────────────────────────────────────────


class CommandHITLRespondData(_CmdBase):
    """Resolve a pending ``hitl.request``.

    ``decision`` must match the options listed in the original ``hitl.request``
    (e.g. ``accept``/``reject``/``allowlist`` for tool gates).  Unknown values
    normalise to ``reject`` — the runtime never auto-approves on bad input.
    ``text`` carries a free-text answer for ``clarification`` kind gates.
    """

    request_id: str
    decision: str = "reject"
    text: str | None = None
    actor: str = "user"


class CommandHITLRespond(_CmdBase):
    type: Literal["command.hitl.respond"] = "command.hitl.respond"
    data: CommandHITLRespondData


# ── command.runtime.shutdown ───────────────────────────────────────────────────


class CommandRuntimeShutdownData(_CmdBase):
    """Graceful exit. Cancels in-flight invocations, resolves pending HITL gates
    as ``cancelled``, emits ``session.closed(reason="shutdown")``, and exits."""



class CommandRuntimeShutdown(_CmdBase):
    type: Literal["command.runtime.shutdown"] = "command.runtime.shutdown"
    data: CommandRuntimeShutdownData = Field(default_factory=CommandRuntimeShutdownData)


# ── command.worker.assign ──────────────────────────────────────────────────────


class CommandWorkerAssignData(_CmdBase):
    """Assign a task to a worker.

    In Phase 1 (single-process) the runtime spawns an in-process agent and maps
    results back onto the session via ``worker.*`` events. In Phase 2 (distributed)
    this command routes to a remote worker node identified by ``worker_id``; the
    node emits results back through the same AGP session.

    ``parent_thread`` is the supervisor's thread id — used to correlate worker
    events to the originating invocation when multiple invocations run concurrently.
    """

    worker_id: str
    task: str
    thread: str | None = None          # the worker's own thread (minted by runtime if absent)
    parent_thread: str | None = None   # supervisor's thread for correlation
    pattern: str | None = None         # hint for which pattern the worker should use
    tools: list[str] = Field(default_factory=list)
    context: dict[str, Any] | None = None


class CommandWorkerAssign(_CmdBase):
    type: Literal["command.worker.assign"] = "command.worker.assign"
    data: CommandWorkerAssignData


# ── command.session.resume ─────────────────────────────────────────────────────


class CommandSessionResumeData(_CmdBase):
    """Reconnect to an existing session.

    The runtime emits ``session.resumed`` (not ``session.opened``) and replays
    any buffered events since ``from_seq`` so the client catches up.  When
    ``from_seq`` is absent the runtime only emits ``session.resumed`` without
    replaying past events.
    """

    thread: str
    from_seq: int | None = None


class CommandSessionResume(_CmdBase):
    type: Literal["command.session.resume"] = "command.session.resume"
    data: CommandSessionResumeData


# ── command.feedback ───────────────────────────────────────────────────────────


class CommandFeedbackData(_CmdBase):
    """Submit user feedback for a completed turn.

    ``run_id`` identifies the agent invocation to rate (from ``message.assistant.run_id``).
    ``rating`` is a string token: ``"positive"`` / ``"negative"`` / ``"neutral"`` or a numeric
    string (``"5"``).  ``comment`` and ``correct`` carry free-text elaboration.
    ``metadata`` is an optional pass-through dict stored alongside the rating.
    """

    run_id: str
    rating: str
    comment: str = ""
    correct: str = ""
    metadata: dict[str, Any] | None = None


class CommandFeedback(_CmdBase):
    type: Literal["command.feedback"] = "command.feedback"
    data: CommandFeedbackData


# ── command.snapshot.request ───────────────────────────────────────────────────


class CommandSnapshotRequestData(_CmdBase):
    """Ask the runtime to save a LangGraph checkpoint and emit ``checkpoint.saved``.

    ``thread`` identifies which conversation thread to snapshot. When absent, the most
    recently active thread on this session is used. ``label`` is a human-readable tag
    stored in the checkpoint metadata.
    """

    thread: str | None = None
    label: str | None = None


class CommandSnapshotRequest(_CmdBase):
    type: Literal["command.snapshot.request"] = "command.snapshot.request"
    data: CommandSnapshotRequestData = Field(default_factory=CommandSnapshotRequestData)


# ── Discriminated union & adapter ─────────────────────────────────────────────


Command = Annotated[
    CommandInvoke
    | CommandCancel
    | CommandHITLRespond
    | CommandRuntimeShutdown
    | CommandWorkerAssign
    | CommandSessionResume
    | CommandFeedback
    | CommandSnapshotRequest,
    Field(discriminator="type"),
]
"""Discriminated union over all known AGP command types.

Use :data:`command_adapter` to parse inbound JSON lines::

    cmd = command_adapter.validate_python(json.loads(line))
"""


command_adapter: TypeAdapter[Command] = TypeAdapter(Command)
"""``TypeAdapter`` for parsing AGP commands from JSON / dicts."""


__all__ = [
    "Command",
    "CommandCancel",
    "CommandCancelData",
    "CommandFeedback",
    "CommandFeedbackData",
    "CommandHITLRespond",
    "CommandHITLRespondData",
    "CommandInvoke",
    "CommandInvokeData",
    "CommandRuntimeShutdown",
    "CommandRuntimeShutdownData",
    "CommandSessionResume",
    "CommandSessionResumeData",
    "CommandSnapshotRequest",
    "CommandSnapshotRequestData",
    "CommandWorkerAssign",
    "CommandWorkerAssignData",
    "command_adapter",
]
