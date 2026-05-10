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
- ``checkpoint.*`` — LangGraph checkpoint persistence
- ``feedback.*`` — user feedback on a completed turn
- ``metric.*`` — token/cost accounting deltas
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
    capabilities: list[str] = Field(default_factory=list)


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


class MessageUserData(_DataBase):
    """Inbound user prompt — emitted once per ``command.invoke`` so the wire records the turn."""

    content: str
    message_id: str | None = None


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
    """

    tool: str
    tool_call_id: str
    output_preview: str = ""
    output_bytes: int | None = None
    duration_ms: int | None = None
    truncated: bool = False


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
    capabilities: list[str] = Field(default_factory=list)
    resumed_from_thread: str | None = None
    replayed_from_seq: int | None = None


class SessionResumed(Envelope):
    type: Literal["session.resumed"] = "session.resumed"
    data: SessionResumedData


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
    | PatternClassified
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
    | MemorySessionWrite
    | MemoryLtRecall
    | MemoryLtStore
    | CheckpointSaved
    | CheckpointRestored
    | FeedbackScored
    | MetricTokens
    | MetricCost
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
    "MessageAssistant",
    "MessageAssistantData",
    "MessageUser",
    "MessageUserData",
    "MetricCost",
    "MetricCostData",
    "MetricTokens",
    "MetricTokensData",
    "PatternClassified",
    "PatternClassifiedData",
    "SessionCloseReason",
    "SessionClosed",
    "SessionClosedData",
    "SessionOpened",
    "SessionOpenedData",
    "SessionResumed",
    "SessionResumedData",
    "ThinkingStep",
    "ThinkingStepData",
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
