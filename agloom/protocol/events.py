"""AGP event types — full event catalogue.

Each concrete event type is a Pydantic model that extends :class:`agloom.protocol.envelope.Envelope`
with two additions:

- ``type`` — a ``Literal`` string (the discriminator)
- ``data`` — a typed payload model

The :data:`Event` type alias is a discriminated union over ``type``; use it (or the
:data:`event_adapter` ``TypeAdapter``) to parse arbitrary AGP events from the wire.

**Event domains shipped**:

- ``session.*`` — lifecycle (opened, resumed, closed)
- ``pattern.*`` — classifier output
- ``thinking.*`` — reasoning trace lines
- ``token.*`` — incremental LLM tokens
- ``message.*`` — user/assistant messages (user + assistant)
- ``tool.*`` — tool execution lifecycle
- ``hitl.*`` — human-in-the-loop gates and decisions
- ``worker.*`` — multi-agent worker tree (spawned, completed, failed)
- ``graph.*`` — execution DAG node enter/exit
- ``memory.*`` — session and long-term memory reads/writes
- ``skill.*`` — skill registry lifecycle (loaded into context, classifier injection, learned)
- ``prompt.*`` — user-turn prompt lifecycle (requested, cancelled)
- ``checkpoint.*`` — LangGraph checkpoint persistence
- ``feedback.*`` — user feedback on a completed turn
- ``metric.*`` — token/cost accounting deltas
- ``runtime.*`` — runtime readiness, config snapshot, control-plane replies (pong, schema, tools)
- ``session.heartbeat`` — periodic keep-alive / uptime hints
- ``agent.*`` — busy/idle markers around invocations
- ``message.tool`` — coarse tool progress (alongside ``tool.call.*``)
- ``stream.heartbeat`` — optional streaming liveness
- ``error.*`` — transient and fatal errors

New event types are additive — existing types stay stable.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from .envelope import Envelope


class _DataBase(BaseModel):
    model_config = ConfigDict(extra="allow")  # forward-compatible: tolerate extra fields on data


# ── session.opened ────────────────────────────────────────────────────────────


class SessionOpenedData(_DataBase):
    runtime_version: str
    protocol_version: str
    capabilities_override: list[str] | None = Field(
        default=None,
        description=(
            "Optional session-level capability hints. When present, clients SHOULD apply these "
            "on top of or instead of ``runtime.config.capabilities`` per product policy."
        ),
    )


class SessionOpened(Envelope):
    type: Literal["session.opened"] = "session.opened"
    data: SessionOpenedData


# ── pattern.classified ────────────────────────────────────────────────────────


class PatternClassifiedData(_DataBase):
    pattern: str  # e.g. "REACT", "SUPERVISOR" — see :class:`agloom.PatternType`
    complexity: int | None = None
    confidence: float | None = None
    reason: str | None = None


class PatternClassified(Envelope):
    type: Literal["pattern.classified"] = "pattern.classified"
    data: PatternClassifiedData


# ── plan.preview ───────────────────────────────────────────────────────────────


class PlanPreviewData(_DataBase):
    """Classifier-only plan (``command.plan.preview``); does not run tools or patterns."""

    pattern: str
    complexity: int = 0
    reasoning: str = ""
    steps: list[str] = Field(default_factory=list)


class PlanPreview(Envelope):
    type: Literal["plan.preview"] = "plan.preview"
    data: PlanPreviewData


# ── thinking.step ─────────────────────────────────────────────────────────────


class ThinkingStepData(_DataBase):
    step: str  # e.g. "analyze_query", "classify"
    label: str | None = None
    detail: str | None = None
    elapsed_ms: int | None = None


class ThinkingStep(Envelope):
    type: Literal["thinking.step"] = "thinking.step"
    data: ThinkingStepData


# ── token.delta ───────────────────────────────────────────────────────────────


class TokenDeltaData(_DataBase):
    text: str
    role: Literal["assistant", "tool"] = "assistant"
    message_id: str | None = None


class TokenDelta(Envelope):
    type: Literal["token.delta"] = "token.delta"
    data: TokenDeltaData


# ── message.assistant ─────────────────────────────────────────────────────────


class MessageAssistantData(_DataBase):
    content: str
    message_id: str | None = None
    run_id: str | None = None
    pattern: str | None = None


class MessageAssistant(Envelope):
    type: Literal["message.assistant"] = "message.assistant"
    data: MessageAssistantData


# ── session.closed ────────────────────────────────────────────────────────────


SessionCloseReason = Literal["completed", "user_aborted", "error", "shutdown"]


class SessionClosedData(_DataBase):
    reason: SessionCloseReason
    duration_ms: int | None = None
    error: str | None = None


class SessionClosed(Envelope):
    type: Literal["session.closed"] = "session.closed"
    data: SessionClosedData


# ── message.user ──────────────────────────────────────────────────────────────


class MessageUserAttachmentSummary(_DataBase):
    """Small attachment record for transcript replay (no raw bytes on the wire)."""

    name: str
    mime_type: str
    byte_length: int = 0
    path: str | None = None


class MessageUserData(_DataBase):
    """Inbound user prompt — emitted once per ``command.invoke`` so the wire records the turn."""

    content: str
    message_id: str | None = None
    attachments: list[MessageUserAttachmentSummary] | None = None


class MessageUser(Envelope):
    type: Literal["message.user"] = "message.user"
    data: MessageUserData


# ── tool.* ────────────────────────────────────────────────────────────────────


class ToolCallStartData(_DataBase):
    """Agent decided to invoke a tool — pre-execution. Emitted whether or not HITL gates it."""

    tool: str
    tool_call_id: str
    args: dict[str, Any] = Field(default_factory=dict)
    worker: str | None = None  # populated when this tool runs inside a worker (SUPERVISOR/SWARM)


class ToolCallStart(Envelope):
    type: Literal["tool.call.start"] = "tool.call.start"
    data: ToolCallStartData


class ToolCallResultData(_DataBase):
    """Tool finished successfully. ``output_preview`` is truncated; full content lives in
    :class:`ToolCallStart` via correlation by ``tool_call_id``.

    Optional ``diff`` carries file before/after for edit tools (wire + UI).
    """

    tool: str
    tool_call_id: str
    output_preview: str = ""
    output_bytes: int | None = None
    duration_ms: int | None = None
    truncated: bool = False
    diff: dict[str, Any] | None = None


class ToolCallResult(Envelope):
    type: Literal["tool.call.result"] = "tool.call.result"
    data: ToolCallResultData


class ToolCallErrorData(_DataBase):
    tool: str
    tool_call_id: str
    error: str
    error_class: str | None = None
    duration_ms: int | None = None


class ToolCallError(Envelope):
    type: Literal["tool.call.error"] = "tool.call.error"
    data: ToolCallErrorData


# ── worker.* ──────────────────────────────────────────────────────────────────


class WorkerSpawnedData(_DataBase):
    """A worker has been created — used by SUPERVISOR / SWARM / BLACKBOARD / HYBRID_DAG patterns
    to render an agent tree. ``parent_worker_id`` is set for nested supervision; root workers
    leave it ``None``.
    """

    worker_id: str
    name: str | None = None
    pattern: str | None = None  # e.g. "SUPERVISOR" — the pattern that spawned it
    task: str | None = None  # human-readable assignment
    parent_worker_id: str | None = None


class WorkerSpawned(Envelope):
    type: Literal["worker.spawned"] = "worker.spawned"
    data: WorkerSpawnedData


class WorkerCompletedData(_DataBase):
    worker_id: str
    output_preview: str = ""
    output_bytes: int | None = None
    duration_ms: int | None = None
    truncated: bool = False


class WorkerCompleted(Envelope):
    type: Literal["worker.completed"] = "worker.completed"
    data: WorkerCompletedData


class WorkerFailedData(_DataBase):
    worker_id: str
    error: str
    error_class: str | None = None
    duration_ms: int | None = None


class WorkerFailed(Envelope):
    type: Literal["worker.failed"] = "worker.failed"
    data: WorkerFailedData


# ── metric.* ──────────────────────────────────────────────────────────────────


class MetricTokensData(_DataBase):
    """Token usage **delta** for one LLM call. Frontends sum across the session for the sidebar
    rollup. ``phase`` distinguishes classifier / react / reflection / synthesizer billing.
    """

    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int | None = None  # may be reported by some providers; otherwise frontends sum
    phase: str | None = None  # e.g. "classify", "react", "reflection", "synthesizer"
    worker_id: str | None = None


class MetricTokens(Envelope):
    type: Literal["metric.tokens"] = "metric.tokens"
    data: MetricTokensData


class MetricCostData(_DataBase):
    """Cost **delta** for one billable unit (LLM call, tool call, …). Currency defaults to USD."""

    cost: float
    currency: str = "USD"
    model: str | None = None
    phase: str | None = None
    worker_id: str | None = None


class MetricCost(Envelope):
    type: Literal["metric.cost"] = "metric.cost"
    data: MetricCostData


class MetricBudgetApproachingData(_DataBase):
    """Once per dimension when cumulative usage crosses ~80% of the configured limit."""

    dimension: Literal["tokens", "cost_usd"]
    used: float
    limit: float
    ratio: float


class MetricBudgetApproaching(Envelope):
    type: Literal["metric.budget.approaching"] = "metric.budget.approaching"
    data: MetricBudgetApproachingData


class MetricBudgetExhaustedData(_DataBase):
    """When cumulative usage reaches the limit; runtime may block further invokes."""

    dimension: Literal["tokens", "cost_usd"]
    used: float
    limit: float


class MetricBudgetExhausted(Envelope):
    type: Literal["metric.budget.exhausted"] = "metric.budget.exhausted"
    data: MetricBudgetExhaustedData


# ── hitl.* ────────────────────────────────────────────────────────────────────


HITLKind = Literal[
    "tool_approval",
    "pattern_approval",
    "worker_approval",
    "react_recovery",
    "clarification",
]
"""The shape of an HITL gate. ``tool_approval`` covers the canonical approve/deny/allowlist card;
``clarification`` expects a free-text answer instead of a discrete decision; ``react_recovery``
is the post-``tool_use_failed`` retry-or-stop prompt (no real tool exists yet to allowlist)."""


HITLDecision = Literal["accept", "reject", "allowlist", "retry", "stop", "timeout", "cancelled"]
"""Decision tokens accepted on the wire. Not every kind admits every value:

- ``tool_approval``, ``pattern_approval``, ``worker_approval``: ``accept`` / ``reject`` / ``allowlist``
- ``react_recovery``: ``retry`` / ``stop``
- ``clarification``: not applicable — the response carries free text instead
- ``timeout`` / ``cancelled`` are runtime-emitted only (frontends should not send these)
"""


class HITLRequestData(_DataBase):
    """Runtime asks the user to gate something. The frontend MUST reply with
    ``command.hitl.respond`` carrying the same ``request_id``; the runtime blocks the agent
    until the response arrives (or the optional ``timeout_ms`` elapses)."""

    request_id: str
    kind: HITLKind
    detail: str | None = None
    options: list[str] = Field(default_factory=list)
    default: str | None = None
    timeout_ms: int | None = None  # when set, the runtime auto-resolves with decision="timeout" after this many ms
    agent_name: str | None = None
    # Tool-approval extras (populated when ``kind == "tool_approval"``):
    tool: str | None = None
    tool_call_id: str | None = None  # correlates with the matching ``tool.call.start.data.tool_call_id``
    args: dict[str, Any] = Field(default_factory=dict)
    # Worker / pattern extras:
    worker: str | None = None
    pattern: str | None = None
    # Clarification extras:
    question: str | None = None


class HITLRequest(Envelope):
    type: Literal["hitl.request"] = "hitl.request"
    data: HITLRequestData


class HITLDecisionData(_DataBase):
    """Outcome event emitted by the runtime *after* it received and applied the response.

    For ``clarification`` kind, the user's free-text answer rides in ``text``. For all other
    kinds, ``decision`` is the discrete choice. Either way, ``request_id`` correlates to the
    original :class:`HITLRequest`.
    """

    request_id: str
    decision: HITLDecision
    actor: Literal["user", "auto", "timeout"] = "user"
    text: str | None = None  # for ``clarification`` kind
    detail: str | None = None  # human-readable note (e.g. "added to project allowlist")


class HITLGranted(Envelope):
    """User accepted the gate; the runtime proceeds with the underlying action."""

    type: Literal["hitl.granted"] = "hitl.granted"
    data: HITLDecisionData


class HITLDenied(Envelope):
    """User rejected; the runtime aborts the action."""

    type: Literal["hitl.denied"] = "hitl.denied"
    data: HITLDecisionData


class HITLAllowlisted(Envelope):
    """User accepted *and* asked to skip future prompts for this scope (tool / pattern / worker)."""

    type: Literal["hitl.allowlisted"] = "hitl.allowlisted"
    data: HITLDecisionData


# ── memory.* ──────────────────────────────────────────────────────────────────


class MemorySessionWriteData(_DataBase):
    """A turn was persisted into session (short-term) memory.

    ``turn_count`` is the number of turns now stored for this thread.
    ``query_preview`` and ``output_preview`` are truncated to 200 chars.
    """

    thread: str
    run_id: str | None = None
    query_preview: str | None = None
    output_preview: str | None = None
    turn_count: int | None = None


class MemorySessionWrite(Envelope):
    type: Literal["memory.session.write"] = "memory.session.write"
    data: MemorySessionWriteData


class MemorySessionClearedData(_DataBase):
    """Short-term session memory for *thread* was cleared (no turns remain)."""

    thread: str


class MemorySessionCleared(Envelope):
    type: Literal["memory.session.cleared"] = "memory.session.cleared"
    data: MemorySessionClearedData


class MemorySessionTurnPoppedData(_DataBase):
    """One short-term session turn was removed (e.g. user ``/undo`` in the CLI)."""

    thread: str
    remaining_turns: int


class MemorySessionTurnPopped(Envelope):
    type: Literal["memory.session.turn_popped"] = "memory.session.turn_popped"
    data: MemorySessionTurnPoppedData


class MemoryLtRecallData(_DataBase):
    """Long-term memory was searched to build the query context.

    ``hits`` is the number of results injected. ``namespace`` is the LT namespace.
    """

    namespace: str | None = None
    query_preview: str | None = None
    hits: int = 0
    injected_chars: int = 0


class MemoryLtRecall(Envelope):
    type: Literal["memory.lt.recall"] = "memory.lt.recall"
    data: MemoryLtRecallData


class MemoryLtStoreData(_DataBase):
    """A fact was persisted into long-term memory.

    ``key`` is the storage key; ``namespace`` is the LT namespace.
    """

    namespace: str | None = None
    key: str | None = None
    content_preview: str | None = None


class MemoryLtStore(Envelope):
    type: Literal["memory.lt.store"] = "memory.lt.store"
    data: MemoryLtStoreData


# ── checkpoint.* ──────────────────────────────────────────────────────────────


class CheckpointSavedData(_DataBase):
    """A LangGraph checkpoint was successfully persisted.

    Emitted after every successful ``_save_checkpoint`` call in ``run_fresh``.
    ``label`` is an optional human-readable tag from ``command.snapshot.request``.
    ``run_id`` identifies the agent run that produced this checkpoint.
    """

    thread: str
    run_id: str | None = None
    label: str | None = None


class CheckpointSaved(Envelope):
    type: Literal["checkpoint.saved"] = "checkpoint.saved"
    data: CheckpointSavedData


class CheckpointRestoredData(_DataBase):
    """Emitted when the runtime detects and resumes from an existing LangGraph checkpoint.

    ``resumed_from_run_id`` identifies the previous run that created the checkpoint.
    """

    thread: str
    resumed_from_run_id: str | None = None


class CheckpointRestored(Envelope):
    type: Literal["checkpoint.restored"] = "checkpoint.restored"
    data: CheckpointRestoredData


# ── feedback.* ────────────────────────────────────────────────────────────────


class FeedbackScoredData(_DataBase):
    """A user submitted feedback for a completed turn.

    ``run_id`` correlates to ``message.assistant.run_id``.
    ``rating`` is a string token (``"positive"`` / ``"negative"`` / numeric).
    ``comment`` and ``correct`` are optional free-text elaboration.
    """

    run_id: str
    rating: str
    comment: str = ""
    correct: str = ""
    metadata: dict[str, Any] | None = None


class FeedbackScored(Envelope):
    type: Literal["feedback.scored"] = "feedback.scored"
    data: FeedbackScoredData


# ── graph.* ───────────────────────────────────────────────────────────────────


class GraphNodeEnterData(_DataBase):
    """A LangGraph (or agloom pattern) node has started executing.

    ``node`` is the node name (e.g. ``"classify"``, ``"react"``, ``"synthesize"``).
    ``pattern`` identifies which of the 9 execution patterns owns the node.
    ``input_preview`` is an optional truncated preview of the node's input for
    the execution-DAG pane.
    """

    node: str
    pattern: str | None = None
    input_preview: str | None = None


class GraphNodeEnter(Envelope):
    type: Literal["graph.node.enter"] = "graph.node.enter"
    data: GraphNodeEnterData


class GraphNodeExitData(_DataBase):
    """A LangGraph (or agloom pattern) node has finished.

    ``parent`` SHOULD be the matching ``graph.node.enter`` event id for
    latency-attribution on execution-DAG visualisations.
    """

    node: str
    pattern: str | None = None
    duration_ms: int | None = None
    output_preview: str | None = None
    error: str | None = None  # set when the node raised


class GraphNodeExit(Envelope):
    type: Literal["graph.node.exit"] = "graph.node.exit"
    data: GraphNodeExitData


# ── skill.* ───────────────────────────────────────────────────────────────────


SkillLoadedSource = Literal["tool", "disk", "registry", "seed", "on_demand", "post_run"]


class SkillLoadedData(_DataBase):
    """A skill's full body was loaded (typically via the ``load_skill`` tool)."""

    skill_name: str
    source: SkillLoadedSource = "tool"
    version: str | None = None
    body_chars: int | None = None


class SkillLoaded(Envelope):
    type: Literal["skill.loaded"] = "skill.loaded"
    data: SkillLoadedData


SkillAppliedPhase = Literal["classifier", "worker"]


class SkillAppliedData(_DataBase):
    """Skill-related context was injected into the model prompt (pre-classify catalogue)."""

    phase: SkillAppliedPhase = "classifier"
    injected_chars: int = 0


class SkillApplied(Envelope):
    type: Literal["skill.applied"] = "skill.applied"
    data: SkillAppliedData


SkillLearnedSource = Literal["seed", "on_demand", "post_run"]


class SkillLearnedData(_DataBase):
    """A new or updated skill was persisted to the registry."""

    skill_name: str
    pattern: str | None = None
    scope: str | None = None
    source: SkillLearnedSource | None = None


class SkillLearned(Envelope):
    type: Literal["skill.learned"] = "skill.learned"
    data: SkillLearnedData


# ── prompt.* ──────────────────────────────────────────────────────────────────


PromptRequestedKind = Literal["user_turn"]


class PromptRequestedData(_DataBase):
    """The runtime accepted a user turn and will stream agent work for this thread."""

    kind: PromptRequestedKind = "user_turn"
    preview: str | None = None


class PromptRequested(Envelope):
    type: Literal["prompt.requested"] = "prompt.requested"
    data: PromptRequestedData


PromptCancelledReason = Literal["user_aborted", "shutdown"]


class PromptCancelledData(_DataBase):
    """The in-flight user turn will not produce a normal assistant completion."""

    reason: PromptCancelledReason
    detail: str | None = None


class PromptCancelled(Envelope):
    type: Literal["prompt.cancelled"] = "prompt.cancelled"
    data: PromptCancelledData


# ── session.resumed ────────────────────────────────────────────────────────────


class SessionResumedData(_DataBase):
    """A client has reconnected to an existing session.

    Emitted instead of ``session.opened`` when the runtime detects a known
    ``thread_id`` (LangGraph checkpoint exists) or when a ``command.session.resume``
    is received.  ``resumed_from_thread`` is the thread the client was previously
    connected to.  ``replayed_from_seq`` is the first sequence number replayed from
    the :class:`~agloom.protocol.store.EventStore` (absent when no replay was done).
    """

    runtime_version: str
    protocol_version: str
    capabilities_override: list[str] | None = Field(
        default=None,
        description="Same semantics as :attr:`SessionOpenedData.capabilities_override` on reconnect.",
    )
    resumed_from_thread: str | None = None
    replayed_from_seq: int | None = None


class SessionResumed(Envelope):
    type: Literal["session.resumed"] = "session.resumed"
    data: SessionResumedData


# ── runtime.* (lifecycle + control-plane replies) ─────────────────────────────


class RuntimeReadyData(_DataBase):
    agent_name: str | None = None
    cli_tools_enabled: bool | None = None
    cli_tools_count: int | None = None
    harness_enabled: bool | None = None


class RuntimeReady(Envelope):
    type: Literal["runtime.ready"] = "runtime.ready"
    data: RuntimeReadyData


class RuntimeConfigData(_DataBase):
    model_id: str | None = None
    tool_names: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(
        default_factory=list,
        description="Canonical capability tokens advertised by this runtime attachment.",
    )
    cli_tools_enabled: bool | None = None
    cli_tools_count: int | None = None


class RuntimeConfig(Envelope):
    type: Literal["runtime.config"] = "runtime.config"
    data: RuntimeConfigData


class RuntimePongData(_DataBase):
    ping_id: str | None = None


class RuntimePong(Envelope):
    type: Literal["runtime.pong"] = "runtime.pong"
    data: RuntimePongData


class RuntimeSchemaPayloadData(_DataBase):
    json_schema: dict[str, Any] = Field(default_factory=dict)


class RuntimeSchemaPayload(Envelope):
    type: Literal["runtime.schema"] = "runtime.schema"
    data: RuntimeSchemaPayloadData


class RuntimeToolEntry(_DataBase):
    name: str
    description: str | None = None


class RuntimeToolsPayloadData(_DataBase):
    tools: list[RuntimeToolEntry] = Field(default_factory=list)


class RuntimeToolsPayload(Envelope):
    type: Literal["runtime.tools"] = "runtime.tools"
    data: RuntimeToolsPayloadData


class RuntimeProviderEntry(_DataBase):
    """One curated provider row (from :func:`agloom.llm.provider_registry.provider_catalog`)."""

    slug: str
    label: str
    default_model: str
    primary_env_key: str | None = None


class RuntimeProvidersPayloadData(_DataBase):
    providers: list[RuntimeProviderEntry] = Field(default_factory=list)


class RuntimeProvidersPayload(Envelope):
    type: Literal["runtime.providers"] = "runtime.providers"
    data: RuntimeProvidersPayloadData


class RuntimeSessionsPayloadData(_DataBase):
    sessions: list[str] = Field(default_factory=list)


class RuntimeSessionsPayload(Envelope):
    type: Literal["runtime.sessions"] = "runtime.sessions"
    data: RuntimeSessionsPayloadData


class RuntimeSessionCreatedData(_DataBase):
    session_id: str


class RuntimeSessionCreated(Envelope):
    type: Literal["runtime.session.created"] = "runtime.session.created"
    data: RuntimeSessionCreatedData


class RuntimeSessionRenamedData(_DataBase):
    from_session_id: str
    to_session_id: str


class RuntimeSessionRenamed(Envelope):
    type: Literal["runtime.session.renamed"] = "runtime.session.renamed"
    data: RuntimeSessionRenamedData


class RuntimeFileStagedData(_DataBase):
    """A client attachment was written under the agent working directory."""

    path: str
    bytes: int
    thread: str | None = None


class RuntimeFileStaged(Envelope):
    type: Literal["runtime.file.staged"] = "runtime.file.staged"
    data: RuntimeFileStagedData


class RuntimeToolInvokeResultData(_DataBase):
    ok: bool
    result: Any | None = None
    error: str | None = None


class RuntimeToolInvokeResult(Envelope):
    type: Literal["runtime.tool.result"] = "runtime.tool.result"
    data: RuntimeToolInvokeResultData


class RuntimeConfigAppliedData(_DataBase):
    model_id: str | None = None
    cli_tools_enabled: bool | None = None
    cli_tools_count: int | None = None


class RuntimeConfigApplied(Envelope):
    type: Literal["runtime.config.applied"] = "runtime.config.applied"
    data: RuntimeConfigAppliedData


class RuntimeMCPServersData(_DataBase):
    """Emitted after MCP servers connect (may be empty if none configured)."""

    server_names: list[str]


class RuntimeMCPServers(Envelope):
    type: Literal["runtime.mcp.servers"] = "runtime.mcp.servers"
    data: RuntimeMCPServersData


class TodosUpdatedData(_DataBase):
    """Session-scoped todo list snapshot (from ``write_todos`` meta tool)."""

    items: list[dict[str, Any]] = Field(default_factory=list)


class TodosUpdated(Envelope):
    type: Literal["todos.updated"] = "todos.updated"
    data: TodosUpdatedData


# ── session.heartbeat ───────────────────────────────────────────────────────────


class SessionHeartbeatData(_DataBase):
    uptime_ms: int | None = None


class SessionHeartbeat(Envelope):
    type: Literal["session.heartbeat"] = "session.heartbeat"
    data: SessionHeartbeatData


# ── agent.busy / agent.idle ─────────────────────────────────────────────────────


class AgentBusyData(_DataBase):
    thread: str | None = None


class AgentBusy(Envelope):
    type: Literal["agent.busy"] = "agent.busy"
    data: AgentBusyData


class AgentIdleData(_DataBase):
    thread: str | None = None


class AgentIdle(Envelope):
    type: Literal["agent.idle"] = "agent.idle"
    data: AgentIdleData


# ── message.tool (human-readable tool progress, complements tool.call.*) ──────


class MessageToolData(_DataBase):
    tool_name: str
    phase: Literal["start", "progress", "end"] = "progress"
    detail: str | None = None
    call_id: str | None = None


class MessageTool(Envelope):
    type: Literal["message.tool"] = "message.tool"
    data: MessageToolData


# ── stream.heartbeat ────────────────────────────────────────────────────────────


class StreamHeartbeatData(_DataBase):
    thread: str | None = None
    chars_since_last: int | None = None


class StreamHeartbeat(Envelope):
    type: Literal["stream.heartbeat"] = "stream.heartbeat"
    data: StreamHeartbeatData


# ── error.* ───────────────────────────────────────────────────────────────────


ErrorSeverity = Literal["transient", "fatal"]


class ErrorData(_DataBase):
    """A runtime error surfaced to the frontend. ``fatal`` kills the session; ``transient`` does
    not (e.g. a tool retry, a rate-limit backoff)."""

    severity: ErrorSeverity
    message: str
    error_class: str | None = None
    stage: str | None = None  # e.g. "classify", "react", "tool", "stream"
    retryable: bool = False


class ErrorEvent(Envelope):
    """``type="error.transient"`` or ``"error.fatal"`` — discriminator follows ``data.severity``.

    The on-the-wire ``type`` is set explicitly per emit; we keep two Pydantic classes so the
    discriminated union stays well-formed.
    """

    type: Literal["error.transient", "error.fatal"]
    data: ErrorData


class ErrorTransient(Envelope):
    type: Literal["error.transient"] = "error.transient"
    data: ErrorData


class ErrorFatal(Envelope):
    type: Literal["error.fatal"] = "error.fatal"
    data: ErrorData


# ── Discriminated union & adapter ─────────────────────────────────────────────


Event = Annotated[
    SessionOpened
    | SessionResumed
    | RuntimeReady
    | RuntimeConfig
    | RuntimePong
    | RuntimeSchemaPayload
    | RuntimeToolsPayload
    | RuntimeProvidersPayload
    | RuntimeSessionsPayload
    | RuntimeSessionCreated
    | RuntimeSessionRenamed
    | RuntimeFileStaged
    | RuntimeToolInvokeResult
    | RuntimeConfigApplied
    | RuntimeMCPServers
    | TodosUpdated
    | SessionHeartbeat
    | AgentBusy
    | AgentIdle
    | MessageTool
    | StreamHeartbeat
    | PatternClassified
    | PlanPreview
    | ThinkingStep
    | TokenDelta
    | MessageUser
    | MessageAssistant
    | ToolCallStart
    | ToolCallResult
    | ToolCallError
    | HITLRequest
    | HITLGranted
    | HITLDenied
    | HITLAllowlisted
    | WorkerSpawned
    | WorkerCompleted
    | WorkerFailed
    | GraphNodeEnter
    | GraphNodeExit
    | SkillLoaded
    | SkillApplied
    | SkillLearned
    | PromptRequested
    | PromptCancelled
    | MemorySessionWrite
    | MemorySessionCleared
    | MemorySessionTurnPopped
    | MemoryLtRecall
    | MemoryLtStore
    | CheckpointSaved
    | CheckpointRestored
    | FeedbackScored
    | MetricTokens
    | MetricCost
    | MetricBudgetApproaching
    | MetricBudgetExhausted
    | ErrorTransient
    | ErrorFatal
    | SessionClosed,
    Field(discriminator="type"),
]
"""Discriminated union over all known AGP event types.

Use :data:`event_adapter` (``TypeAdapter[Event]``) to parse JSON wire bytes into a concrete
event instance. Unknown ``type`` strings will raise — consumers wanting forward compatibility
should fall back to a generic ``dict`` parse path.
"""


event_adapter: TypeAdapter[Event] = TypeAdapter(Event)
"""``TypeAdapter`` for parsing AGP events from JSON / dicts."""


__all__ = [
    "AgentBusy",
    "AgentBusyData",
    "AgentIdle",
    "AgentIdleData",
    "MessageTool",
    "MessageToolData",
    "PromptCancelled",
    "PromptCancelledData",
    "PromptCancelledReason",
    "PromptRequested",
    "PromptRequestedData",
    "PromptRequestedKind",
    "SkillApplied",
    "SkillAppliedData",
    "SkillAppliedPhase",
    "SkillLearned",
    "SkillLearnedData",
    "SkillLearnedSource",
    "SkillLoaded",
    "SkillLoadedData",
    "SkillLoadedSource",
    "StreamHeartbeat",
    "StreamHeartbeatData",
    "CheckpointRestored",
    "CheckpointRestoredData",
    "CheckpointSaved",
    "CheckpointSavedData",
    "ErrorData",
    "ErrorEvent",
    "ErrorFatal",
    "ErrorSeverity",
    "ErrorTransient",
    "Event",
    "FeedbackScored",
    "FeedbackScoredData",
    "GraphNodeEnter",
    "GraphNodeEnterData",
    "GraphNodeExit",
    "GraphNodeExitData",
    "HITLAllowlisted",
    "HITLDecision",
    "HITLDecisionData",
    "HITLDenied",
    "HITLGranted",
    "HITLKind",
    "HITLRequest",
    "HITLRequestData",
    "MemoryLtRecall",
    "MemoryLtRecallData",
    "MemoryLtStore",
    "MemoryLtStoreData",
    "MemorySessionWrite",
    "MemorySessionWriteData",
    "MemorySessionCleared",
    "MemorySessionClearedData",
    "MemorySessionTurnPopped",
    "MemorySessionTurnPoppedData",
    "MessageAssistant",
    "MessageAssistantData",
    "MessageUser",
    "MessageUserAttachmentSummary",
    "MessageUserData",
    "MetricBudgetApproaching",
    "MetricBudgetApproachingData",
    "MetricBudgetExhausted",
    "MetricBudgetExhaustedData",
    "MetricCost",
    "MetricCostData",
    "MetricTokens",
    "MetricTokensData",
    "RuntimeConfig",
    "RuntimeConfigApplied",
    "RuntimeConfigAppliedData",
    "RuntimeConfigData",
    "RuntimeMCPServers",
    "RuntimeMCPServersData",
    "RuntimeFileStaged",
    "RuntimeFileStagedData",
    "RuntimePong",
    "RuntimePongData",
    "RuntimeProviderEntry",
    "RuntimeProvidersPayload",
    "RuntimeProvidersPayloadData",
    "RuntimeReady",
    "RuntimeReadyData",
    "RuntimeSchemaPayload",
    "RuntimeSchemaPayloadData",
    "RuntimeSessionCreated",
    "RuntimeSessionCreatedData",
    "RuntimeSessionRenamed",
    "RuntimeSessionRenamedData",
    "RuntimeSessionsPayload",
    "RuntimeSessionsPayloadData",
    "RuntimeToolEntry",
    "RuntimeToolInvokeResult",
    "RuntimeToolInvokeResultData",
    "RuntimeToolsPayload",
    "RuntimeToolsPayloadData",
    "PatternClassified",
    "PatternClassifiedData",
    "PlanPreview",
    "PlanPreviewData",
    "SessionCloseReason",
    "SessionClosed",
    "SessionClosedData",
    "SessionHeartbeat",
    "SessionHeartbeatData",
    "SessionOpened",
    "SessionOpenedData",
    "SessionResumed",
    "SessionResumedData",
    "ThinkingStep",
    "ThinkingStepData",
    "TodosUpdated",
    "TodosUpdatedData",
    "TokenDelta",
    "TokenDeltaData",
    "ToolCallError",
    "ToolCallErrorData",
    "ToolCallResult",
    "ToolCallResultData",
    "ToolCallStart",
    "ToolCallStartData",
    "WorkerCompleted",
    "WorkerCompletedData",
    "WorkerFailed",
    "WorkerFailedData",
    "WorkerSpawned",
    "WorkerSpawnedData",
    "event_adapter",
]
