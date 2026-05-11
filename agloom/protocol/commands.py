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

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class _CmdBase(BaseModel):
    model_config = ConfigDict(extra="allow")  # forward-compatible: tolerate unknown fields


# ── command.invoke ─────────────────────────────────────────────────────────────


class InvokeAttachment(_CmdBase):
    """Inline file payload (base64). Staged under ``.agloom/attachments/<thread>/`` by the runtime."""

    name: str = "file"
    mime_type: str = "application/octet-stream"
    data_base64: str


class CommandInvokeData(_CmdBase):
    """Start a new agent turn. ``thread`` is optional — the runtime mints one when absent."""

    prompt: str
    thread: str | None = None
    user_id: str | None = None
    context: dict[str, Any] | None = None
    attachments: list[InvokeAttachment] | None = None


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


# ── command.ping ───────────────────────────────────────────────────────────────


class CommandPingData(_CmdBase):
    """Optional correlator echoed back on ``runtime.pong``."""

    ping_id: str | None = None


class CommandPing(_CmdBase):
    type: Literal["command.ping"] = "command.ping"
    data: CommandPingData = Field(default_factory=CommandPingData)


# ── command.schema.request ─────────────────────────────────────────────────────


class CommandSchemaRequestData(_CmdBase):
    """Ask the runtime to emit ``runtime.schema`` (full AGP JSON Schema document)."""


class CommandSchemaRequest(_CmdBase):
    type: Literal["command.schema.request"] = "command.schema.request"
    data: CommandSchemaRequestData = Field(default_factory=CommandSchemaRequestData)


# ── command.tool.list ──────────────────────────────────────────────────────────


class CommandToolListData(_CmdBase):
    """Enumerate tools exposed by the current agent (names + descriptions)."""


class CommandToolList(_CmdBase):
    type: Literal["command.tool.list"] = "command.tool.list"
    data: CommandToolListData = Field(default_factory=CommandToolListData)


# ── command.providers.list ─────────────────────────────────────────────────────


class CommandProvidersListData(_CmdBase):
    """Request the curated provider catalog (slug, label, default model, env key)."""


class CommandProvidersList(_CmdBase):
    type: Literal["command.providers.list"] = "command.providers.list"
    data: CommandProvidersListData = Field(default_factory=CommandProvidersListData)


# ── command.subscribe / command.unsubscribe ──────────────────────────────────────


class CommandSubscribeData(_CmdBase):
    """Restrict streamed events to ``type`` prefixes (session/error/runtime/prompt/hitl always pass)."""

    prefixes: list[str] = Field(default_factory=list)


class CommandSubscribe(_CmdBase):
    type: Literal["command.subscribe"] = "command.subscribe"
    data: CommandSubscribeData


class CommandUnsubscribeData(_CmdBase):
    """Clear subscription filter (restore full stream)."""


class CommandUnsubscribe(_CmdBase):
    type: Literal["command.unsubscribe"] = "command.unsubscribe"
    data: CommandUnsubscribeData = Field(default_factory=CommandUnsubscribeData)


# ── command.session.list / create / delete ───────────────────────────────────────


class CommandSessionListData(_CmdBase):
    """List sessions present in the configured :class:`~agloom.protocol.store.EventStore`."""


class CommandSessionList(_CmdBase):
    type: Literal["command.session.list"] = "command.session.list"
    data: CommandSessionListData = Field(default_factory=CommandSessionListData)


class CommandSessionCreateData(_CmdBase):
    """Mint a new opaque session id (store-backed listing uses ids once events are appended)."""

    session_id: str | None = None


class CommandSessionCreate(_CmdBase):
    type: Literal["command.session.create"] = "command.session.create"
    data: CommandSessionCreateData = Field(default_factory=CommandSessionCreateData)


class CommandSessionDeleteData(_CmdBase):
    """Drop replay buffer rows for ``session_id`` (destructive)."""

    session_id: str


class CommandSessionDelete(_CmdBase):
    type: Literal["command.session.delete"] = "command.session.delete"
    data: CommandSessionDeleteData


class CommandSessionRenameData(_CmdBase):
    """Rewrite stored replay rows from ``from_session_id`` to ``to_session_id``."""

    from_session_id: str
    to_session_id: str


class CommandSessionRename(_CmdBase):
    type: Literal["command.session.rename"] = "command.session.rename"
    data: CommandSessionRenameData


# ── command.attach.file ───────────────────────────────────────────────────────────


class CommandAttachFileData(_CmdBase):
    """Upload a file into the agent's CLI-tools working directory.

    ``content_base64`` is standard base64 (padding optional). The runtime writes to
    ``<working_dir>/.agloom_uploads/<id>_<sanitized_filename>`` and emits
    ``runtime.file.staged`` with a path relative to ``working_dir`` (POSIX slashes).
    """

    filename: str
    content_base64: str
    thread: str | None = None


class CommandAttachFile(_CmdBase):
    type: Literal["command.attach.file"] = "command.attach.file"
    data: CommandAttachFileData


# ── command.tool.invoke ──────────────────────────────────────────────────────────


class CommandToolInvokeData(_CmdBase):
    """Direct tool invocation (bounded — argument JSON size limits enforced by the runtime)."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class CommandToolInvoke(_CmdBase):
    type: Literal["command.tool.invoke"] = "command.tool.invoke"
    data: CommandToolInvokeData


# ── command.config.set ───────────────────────────────────────────────────────────


class CommandConfigSetData(_CmdBase):
    """Hot-reload pieces of agent configuration (model, sampling, routing bias, system prompt).

    At least one field must be set. ``cli_tools`` is reserved for future hot-reconfiguration.

    **Budget** fields (optional): set session token / USD caps (``0`` or negative clears that cap).
    """

    model_id: str | None = None
    cli_tools: dict[str, Any] | None = None
    pattern: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    system_prompt: str | None = None
    budget_token_limit: int | None = None
    budget_cost_usd_limit: float | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> CommandConfigSetData:
        if (
            self.model_id is None
            and self.pattern is None
            and self.temperature is None
            and self.top_p is None
            and self.system_prompt is None
            and self.cli_tools is None
            and self.budget_token_limit is None
            and self.budget_cost_usd_limit is None
        ):
            raise ValueError(
                "command.config.set requires at least one of "
                "model_id, pattern, temperature, top_p, system_prompt, cli_tools, "
                "budget_token_limit, budget_cost_usd_limit"
            )
        return self


class CommandConfigSet(_CmdBase):
    type: Literal["command.config.set"] = "command.config.set"
    data: CommandConfigSetData


# ── command.memory.clear ───────────────────────────────────────────────────────────


class CommandMemoryClearData(_CmdBase):
    """Clear short-term session memory for ``thread`` (LangGraph thread id).

    Omit ``thread`` only when the client cannot infer it — runtimes may reject or no-op.
    """

    thread: str | None = None


class CommandMemoryClear(_CmdBase):
    type: Literal["command.memory.clear"] = "command.memory.clear"
    data: CommandMemoryClearData = Field(default_factory=CommandMemoryClearData)


# ── Discriminated union & adapter ─────────────────────────────────────────────


Command = Annotated[
    CommandInvoke
    | CommandCancel
    | CommandHITLRespond
    | CommandRuntimeShutdown
    | CommandWorkerAssign
    | CommandSessionResume
    | CommandFeedback
    | CommandSnapshotRequest
    | CommandPing
    | CommandSchemaRequest
    | CommandToolList
    | CommandProvidersList
    | CommandSubscribe
    | CommandUnsubscribe
    | CommandSessionList
    | CommandSessionCreate
    | CommandSessionDelete
    | CommandSessionRename
    | CommandAttachFile
    | CommandToolInvoke
    | CommandConfigSet
    | CommandMemoryClear,
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
    "CommandConfigSet",
    "CommandConfigSetData",
    "CommandFeedback",
    "CommandFeedbackData",
    "CommandHITLRespond",
    "CommandHITLRespondData",
    "CommandInvoke",
    "CommandInvokeData",
    "InvokeAttachment",
    "CommandMemoryClear",
    "CommandMemoryClearData",
    "CommandPing",
    "CommandPingData",
    "CommandProvidersList",
    "CommandProvidersListData",
    "CommandRuntimeShutdown",
    "CommandRuntimeShutdownData",
    "CommandSchemaRequest",
    "CommandSchemaRequestData",
    "CommandSessionCreate",
    "CommandSessionCreateData",
    "CommandSessionDelete",
    "CommandSessionDeleteData",
    "CommandSessionRename",
    "CommandSessionRenameData",
    "CommandAttachFile",
    "CommandAttachFileData",
    "CommandSessionList",
    "CommandSessionListData",
    "CommandSessionResume",
    "CommandSessionResumeData",
    "CommandSnapshotRequest",
    "CommandSnapshotRequestData",
    "CommandSubscribe",
    "CommandSubscribeData",
    "CommandToolInvoke",
    "CommandToolInvokeData",
    "CommandToolList",
    "CommandToolListData",
    "CommandUnsubscribe",
    "CommandUnsubscribeData",
    "CommandWorkerAssign",
    "CommandWorkerAssignData",
    "command_adapter",
]
