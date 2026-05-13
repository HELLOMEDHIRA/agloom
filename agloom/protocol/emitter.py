"""SessionEmitter — typed AGP event emitter to a writer (default: stdout).

The emitter owns the ``(session, thread, seq)`` triple and serializes one JSON object per line
(NDJSON). It is the only place that writes to the wire; everything above it constructs typed
events. ``flush`` is called on every emit so events stream out at the rate they're produced.

Thread-safety: a single :class:`threading.Lock` guards the seq counter and the write. Async
code holds the GIL across these short critical sections, so this is fine for stdio. WebSocket
transports replace the writer with their own queue.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from collections.abc import Callable
from typing import IO, Any, Literal

from .envelope import PROTOCOL_MODULE_VERSION, Envelope
from .events import (
    AgentBusy,
    AgentBusyData,
    AgentIdle,
    AgentIdleData,
    CheckpointRestored,
    CheckpointRestoredData,
    CheckpointSaved,
    CheckpointSavedData,
    ErrorData,
    ErrorFatal,
    ErrorSeverity,
    ErrorTransient,
    FeedbackScored,
    FeedbackScoredData,
    GraphNodeEnter,
    GraphNodeEnterData,
    GraphNodeExit,
    GraphNodeExitData,
    HITLAllowlisted,
    HITLDecision,
    HITLDecisionData,
    HITLDenied,
    HITLGranted,
    HITLKind,
    HITLRequest,
    HITLRequestData,
    MemoryLtRecall,
    MemoryLtRecallData,
    MemoryLtStore,
    MemoryLtStoreData,
    MemorySessionCleared,
    MemorySessionClearedData,
    MemorySessionTurnPopped,
    MemorySessionTurnPoppedData,
    MemorySessionWrite,
    MemorySessionWriteData,
    MessageAssistant,
    MessageAssistantData,
    MessageTool,
    MessageToolData,
    MessageUser,
    MessageUserAttachmentSummary,
    MessageUserData,
    MetricBudgetApproaching,
    MetricBudgetApproachingData,
    MetricBudgetExhausted,
    MetricBudgetExhaustedData,
    MetricCost,
    MetricCostData,
    MetricTokens,
    MetricTokensData,
    PatternClassified,
    PatternClassifiedData,
    PlanPreview,
    PlanPreviewData,
    PromptCancelled,
    PromptCancelledData,
    PromptRequested,
    PromptRequestedData,
    RuntimeConfig,
    RuntimeConfigApplied,
    RuntimeConfigAppliedData,
    RuntimeConfigData,
    RuntimeFileStaged,
    RuntimeFileStagedData,
    RuntimePong,
    RuntimePongData,
    RuntimeProviderEntry,
    RuntimeProvidersPayload,
    RuntimeProvidersPayloadData,
    RuntimeReady,
    RuntimeReadyData,
    RuntimeSchemaPayload,
    RuntimeSchemaPayloadData,
    RuntimeSessionCreated,
    RuntimeSessionCreatedData,
    RuntimeSessionRenamed,
    RuntimeSessionRenamedData,
    RuntimeSessionsPayload,
    RuntimeSessionsPayloadData,
    RuntimeToolEntry,
    RuntimeToolInvokeResult,
    RuntimeToolInvokeResultData,
    RuntimeToolsPayload,
    RuntimeToolsPayloadData,
    SessionClosed,
    SessionClosedData,
    SessionCloseReason,
    SessionHeartbeat,
    SessionHeartbeatData,
    SessionOpened,
    SessionOpenedData,
    SessionResumed,
    SessionResumedData,
    SkillApplied,
    SkillAppliedData,
    SkillLearned,
    SkillLearnedData,
    SkillLoaded,
    SkillLoadedData,
    StreamHeartbeat,
    StreamHeartbeatData,
    ThinkingStep,
    ThinkingStepData,
    TodosUpdated,
    TodosUpdatedData,
    TokenDelta,
    TokenDeltaData,
    ToolCallError,
    ToolCallErrorData,
    ToolCallResult,
    ToolCallResultData,
    ToolCallStart,
    ToolCallStartData,
    WorkerCompleted,
    WorkerCompletedData,
    WorkerFailed,
    WorkerFailedData,
    WorkerSpawned,
    WorkerSpawnedData,
)

logger_emitter = logging.getLogger(__name__)


def _store_append_done(t: asyncio.Task) -> None:
    if t.cancelled():
        return
    exc = t.exception()
    if exc is not None:
        logger_emitter.warning("EventStore append task failed: %r", exc)


WriterLike = IO[str]
"""Anything with ``.write(str)`` and ``.flush()`` — typically ``sys.stdout``."""


class _SharedSeq:
    """Monotonic sequence counter shared across all forks of a session.

    The AGP spec says ``seq`` is monotonic *per session* — not per emitter. When one
    :class:`SessionEmitter` forks a sibling via :meth:`SessionEmitter.fork_for_thread`, both
    share the same ``_SharedSeq`` instance so events from concurrent invocations are still
    totally ordered on the session axis.
    """

    __slots__ = ("_lock", "_seq")

    def __init__(self) -> None:
        self._seq = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    @property
    def value(self) -> int:
        return self._seq


class _SubscriptionFilter:
    """Shared mutable prefix filter — forks reference the same instance so ``command.subscribe``
    applies to every thread-bound emitter in the session."""

    __slots__ = ("prefixes",)

    def __init__(self) -> None:
        self.prefixes: list[str] | None = None


class SessionEmitter:
    """Emit AGP events to *writer* as NDJSON.

    Construct one per session. Call :meth:`open` first (emits ``session.opened``), then any of
    the typed ``emit_*`` methods, finally :meth:`close` (emits ``session.closed``). ``open`` and
    ``close`` are idempotent — repeat calls are no-ops.
    """

    def __init__(
        self,
        *,
        session: str,
        thread: str,
        writer: WriterLike | None = None,
        capabilities: list[str] | None = None,
        on_emit: Callable[[Envelope], None] | None = None,
        store: Any | None = None,
        _shared_seq: _SharedSeq | None = None,
        _write_lock: threading.Lock | None = None,
        _sub_filter: _SubscriptionFilter | None = None,
    ) -> None:
        self._session = session
        self._thread = thread
        # Default to stdout when no writer is given. Pass ``None`` explicitly only via the
        # ``_callback_only`` classmethod which sets ``_writer`` directly after construction.
        self._writer: WriterLike | None = writer if writer is not None else sys.stdout
        self._capabilities: list[str] = list(capabilities or [])
        self._on_emit = on_emit
        self._store = store  # optional EventStore for persistence / replay
        self._shared_seq: _SharedSeq = _shared_seq if _shared_seq is not None else _SharedSeq()
        self._write_lock: threading.Lock = _write_lock if _write_lock is not None else threading.Lock()
        self._sub_filter: _SubscriptionFilter = _sub_filter if _sub_filter is not None else _SubscriptionFilter()
        self._opened = False
        self._closed = False

    @classmethod
    def _callback_only(
        cls,
        *,
        session: str,
        thread: str,
        capabilities: list[str] | None = None,
        on_emit: Callable[[Envelope], None] | None = None,
        _shared_seq: _SharedSeq | None = None,
    ) -> SessionEmitter:
        """Create an emitter that only calls ``on_emit`` — no JSON is written anywhere.

        Used by :meth:`UnifiedAgent.astream_agp_events` to get typed AGP event objects
        without the overhead of NDJSON serialisation.
        """
        inst = cls.__new__(cls)
        inst._session = session
        inst._thread = thread
        inst._writer = None
        inst._capabilities = list(capabilities or [])
        inst._on_emit = on_emit
        inst._store = None
        inst._shared_seq = _shared_seq if _shared_seq is not None else _SharedSeq()
        inst._write_lock = threading.Lock()
        inst._sub_filter = _SubscriptionFilter()
        inst._opened = False
        inst._closed = False
        return inst

    # ── lifecycle ────────────────────────────────────────────────────────────

    def open(self, *, capabilities_override: list[str] | None = None) -> SessionOpened:
        """Emit ``session.opened``. Idempotent.

        ``capabilities_override`` is optional; canonical capability tokens belong on
        :meth:`emit_runtime_config`.
        """
        if self._opened:
            return self._last_open  # type: ignore[has-type]
        self._opened = True
        evt = SessionOpened(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            data=SessionOpenedData(
                runtime_version=PROTOCOL_MODULE_VERSION,
                protocol_version="1",
                capabilities_override=capabilities_override,
            ),
        )
        self._write(evt)
        self._last_open = evt
        return evt

    def close(
        self,
        *,
        reason: SessionCloseReason = "completed",
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> SessionClosed | None:
        """Emit ``session.closed``. Idempotent — second call returns ``None``."""
        if self._closed:
            return None
        self._closed = True
        evt = SessionClosed(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            data=SessionClosedData(
                reason=reason,
                duration_ms=duration_ms,
                error=error,
            ),
        )
        self._write(evt)
        return evt

    def resume(
        self,
        *,
        resumed_from_thread: str | None = None,
        replayed_from_seq: int | None = None,
        capabilities_override: list[str] | None = None,
    ) -> SessionResumed:
        """Emit ``session.resumed`` instead of ``session.opened`` on reconnects.

        Marks the emitter as opened so subsequent ``emit_*`` calls proceed normally.
        Use this when the runtime detects a known ``thread_id`` (LangGraph checkpoint
        exists) or on receiving ``command.session.resume``.
        """
        if self._opened:
            return self._last_resume  # type: ignore[has-type]
        self._opened = True
        evt = SessionResumed(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            data=SessionResumedData(
                runtime_version=PROTOCOL_MODULE_VERSION,
                protocol_version="1",
                capabilities_override=capabilities_override,
                resumed_from_thread=resumed_from_thread,
                replayed_from_seq=replayed_from_seq,
            ),
        )
        self._write(evt)
        self._last_resume = evt
        return evt

    # ── typed emit_* shortcuts ───────────────────────────────────────────────

    def emit_pattern_classified(
        self,
        *,
        pattern: str,
        complexity: int | None = None,
        confidence: float | None = None,
        reason: str | None = None,
        parent: str | None = None,
    ) -> PatternClassified:
        evt = PatternClassified(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=PatternClassifiedData(
                pattern=pattern,
                complexity=complexity,
                confidence=confidence,
                reason=reason,
            ),
        )
        self._write(evt)
        return evt

    def emit_plan_preview(
        self,
        *,
        pattern: str,
        complexity: int = 0,
        reasoning: str = "",
        steps: list[str] | None = None,
        parent: str | None = None,
    ) -> PlanPreview:
        """Emit classifier-only plan (``command.plan.preview``)."""
        evt = PlanPreview(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=PlanPreviewData(
                pattern=pattern,
                complexity=complexity,
                reasoning=reasoning,
                steps=list(steps or []),
            ),
        )
        self._write(evt)
        return evt

    def emit_thinking_step(
        self,
        *,
        step: str,
        label: str | None = None,
        detail: str | None = None,
        elapsed_ms: int | None = None,
        parent: str | None = None,
    ) -> ThinkingStep:
        evt = ThinkingStep(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=ThinkingStepData(
                step=step,
                label=label,
                detail=detail,
                elapsed_ms=elapsed_ms,
            ),
        )
        self._write(evt)
        return evt

    def emit_token_delta(
        self,
        *,
        text: str,
        role: str = "assistant",
        message_id: str | None = None,
        parent: str | None = None,
    ) -> TokenDelta:
        evt = TokenDelta(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=TokenDeltaData(
                text=text,
                role=role,  # type: ignore[arg-type]
                message_id=message_id,
            ),
        )
        self._write(evt)
        return evt

    def emit_message_assistant(
        self,
        *,
        content: str,
        message_id: str | None = None,
        run_id: str | None = None,
        pattern: str | None = None,
        parent: str | None = None,
    ) -> MessageAssistant:
        evt = MessageAssistant(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MessageAssistantData(
                content=content,
                message_id=message_id,
                run_id=run_id,
                pattern=pattern,
            ),
        )
        self._write(evt)
        return evt

    def emit_message_user(
        self,
        *,
        content: str,
        message_id: str | None = None,
        parent: str | None = None,
        attachments: list[MessageUserAttachmentSummary] | list[dict[str, Any]] | None = None,
    ) -> MessageUser:
        """Emit the user's prompt as a wire event so the transcript is reproducible from AGP alone."""
        att: list[MessageUserAttachmentSummary] | None = None
        if attachments:
            att = [
                MessageUserAttachmentSummary.model_validate(a) if isinstance(a, dict) else a
                for a in attachments
            ]
        evt = MessageUser(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MessageUserData(content=content, message_id=message_id, attachments=att),
        )
        self._write(evt)
        return evt

    def emit_tool_call_start(
        self,
        *,
        tool: str,
        tool_call_id: str,
        args: dict[str, Any] | None = None,
        worker: str | None = None,
        parent: str | None = None,
    ) -> ToolCallStart:
        """Pre-execution. Emit *before* the tool runs (and before any HITL gate) so the UI can
        render a pending row that ``tool.call.result`` / ``tool.call.error`` later resolves."""
        evt = ToolCallStart(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=ToolCallStartData(
                tool=tool,
                tool_call_id=tool_call_id,
                args=dict(args) if args else {},
                worker=worker,
            ),
        )
        self._write(evt)
        return evt

    def emit_tool_call_result(
        self,
        *,
        tool: str,
        tool_call_id: str,
        output_preview: str = "",
        output_bytes: int | None = None,
        duration_ms: int | None = None,
        truncated: bool = False,
        diff: dict[str, Any] | None = None,
        parent: str | None = None,
    ) -> ToolCallResult:
        """Tool succeeded. ``parent`` SHOULD be the matching ``tool.call.start`` event id."""
        evt = ToolCallResult(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=ToolCallResultData(
                tool=tool,
                tool_call_id=tool_call_id,
                output_preview=output_preview,
                output_bytes=output_bytes,
                duration_ms=duration_ms,
                truncated=truncated,
                diff=diff,
            ),
        )
        self._write(evt)
        return evt

    def emit_tool_call_error(
        self,
        *,
        tool: str,
        tool_call_id: str,
        error: str,
        error_class: str | None = None,
        duration_ms: int | None = None,
        parent: str | None = None,
    ) -> ToolCallError:
        """Tool raised. ``parent`` SHOULD be the matching ``tool.call.start`` event id."""
        evt = ToolCallError(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=ToolCallErrorData(
                tool=tool,
                tool_call_id=tool_call_id,
                error=error,
                error_class=error_class,
                duration_ms=duration_ms,
            ),
        )
        self._write(evt)
        return evt

    def emit_hitl_request(
        self,
        *,
        request_id: str,
        kind: HITLKind,
        detail: str | None = None,
        options: list[str] | None = None,
        default: str | None = None,
        timeout_ms: int | None = None,
        agent_name: str | None = None,
        tool: str | None = None,
        tool_call_id: str | None = None,
        args: dict[str, Any] | None = None,
        worker: str | None = None,
        pattern: str | None = None,
        question: str | None = None,
        parent: str | None = None,
    ) -> HITLRequest:
        """Ask the user to gate something. The frontend MUST reply with ``command.hitl.respond``
        carrying the same ``request_id``."""
        evt = HITLRequest(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=HITLRequestData(
                request_id=request_id,
                kind=kind,
                detail=detail,
                options=list(options or []),
                default=default,
                timeout_ms=timeout_ms,
                agent_name=agent_name,
                tool=tool,
                tool_call_id=tool_call_id,
                args=dict(args) if args else {},
                worker=worker,
                pattern=pattern,
                question=question,
            ),
        )
        self._write(evt)
        return evt

    def emit_hitl_decision(
        self,
        *,
        request_id: str,
        decision: HITLDecision,
        actor: str = "user",
        text: str | None = None,
        detail: str | None = None,
        parent: str | None = None,
    ) -> HITLGranted | HITLDenied | HITLAllowlisted:
        """Emit the outcome of an HITL gate as the appropriate ``hitl.granted``/``denied``/
        ``allowlisted`` event. ``parent`` SHOULD point at the matching ``hitl.request``.

        For ``react_recovery``: ``retry`` → ``hitl.granted``, ``stop`` → ``hitl.denied``.
        For ``clarification``: always ``hitl.granted`` (with ``text`` carrying the answer).
        """
        if decision in ("accept", "retry"):
            cls: type[HITLGranted] | type[HITLDenied] | type[HITLAllowlisted] = HITLGranted
        elif decision == "allowlist":
            cls = HITLAllowlisted
        else:  # reject, stop, timeout, cancelled
            cls = HITLDenied
        evt = cls(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=HITLDecisionData(
                request_id=request_id,
                decision=decision,
                actor=actor,  # type: ignore[arg-type]
                text=text,
                detail=detail,
            ),
        )
        self._write(evt)
        return evt

    def emit_worker_spawned(
        self,
        *,
        worker_id: str,
        name: str | None = None,
        pattern: str | None = None,
        task: str | None = None,
        parent_worker_id: str | None = None,
        parent: str | None = None,
    ) -> WorkerSpawned:
        evt = WorkerSpawned(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=WorkerSpawnedData(
                worker_id=worker_id,
                name=name,
                pattern=pattern,
                task=task,
                parent_worker_id=parent_worker_id,
            ),
        )
        self._write(evt)
        return evt

    def emit_worker_completed(
        self,
        *,
        worker_id: str,
        output_preview: str = "",
        output_bytes: int | None = None,
        duration_ms: int | None = None,
        truncated: bool = False,
        parent: str | None = None,
    ) -> WorkerCompleted:
        """Worker finished. ``parent`` SHOULD be the matching ``worker.spawned`` event id."""
        evt = WorkerCompleted(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=WorkerCompletedData(
                worker_id=worker_id,
                output_preview=output_preview,
                output_bytes=output_bytes,
                duration_ms=duration_ms,
                truncated=truncated,
            ),
        )
        self._write(evt)
        return evt

    def emit_worker_failed(
        self,
        *,
        worker_id: str,
        error: str,
        error_class: str | None = None,
        duration_ms: int | None = None,
        parent: str | None = None,
    ) -> WorkerFailed:
        """Worker raised. ``parent`` SHOULD be the matching ``worker.spawned`` event id."""
        evt = WorkerFailed(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=WorkerFailedData(
                worker_id=worker_id,
                error=error,
                error_class=error_class,
                duration_ms=duration_ms,
            ),
        )
        self._write(evt)
        return evt

    def emit_graph_node_enter(
        self,
        *,
        node: str,
        pattern: str | None = None,
        input_preview: str | None = None,
        parent: str | None = None,
    ) -> GraphNodeEnter:
        """Emit before a node starts executing. ``parent`` SHOULD point at the prior
        ``pattern.classified`` or the parent ``graph.node.exit`` so consumers can
        build the execution DAG edge by edge."""
        evt = GraphNodeEnter(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=GraphNodeEnterData(
                node=node,
                pattern=pattern,
                input_preview=input_preview,
            ),
        )
        self._write(evt)
        return evt

    def emit_graph_node_exit(
        self,
        *,
        node: str,
        pattern: str | None = None,
        duration_ms: int | None = None,
        output_preview: str | None = None,
        error: str | None = None,
        parent: str | None = None,
    ) -> GraphNodeExit:
        """Emit after a node finishes (whether successfully or with an error).
        ``parent`` SHOULD be the matching ``graph.node.enter`` event id."""
        evt = GraphNodeExit(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=GraphNodeExitData(
                node=node,
                pattern=pattern,
                duration_ms=duration_ms,
                output_preview=output_preview,
                error=error,
            ),
        )
        self._write(evt)
        return evt

    def emit_skill_loaded(
        self,
        *,
        skill_name: str,
        source: str = "tool",
        version: str | None = None,
        body_chars: int | None = None,
        parent: str | None = None,
    ) -> SkillLoaded:
        evt = SkillLoaded(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=SkillLoadedData(
                skill_name=skill_name,
                source=source,  # type: ignore[arg-type]
                version=version,
                body_chars=body_chars,
            ),
        )
        self._write(evt)
        return evt

    def emit_skill_applied(
        self,
        *,
        phase: str = "classifier",
        injected_chars: int = 0,
        parent: str | None = None,
    ) -> SkillApplied:
        evt = SkillApplied(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=SkillAppliedData(
                phase=phase,  # type: ignore[arg-type]
                injected_chars=injected_chars,
            ),
        )
        self._write(evt)
        return evt

    def emit_skill_learned(
        self,
        *,
        skill_name: str,
        pattern: str | None = None,
        scope: str | None = None,
        source: str | None = None,
        parent: str | None = None,
    ) -> SkillLearned:
        evt = SkillLearned(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=SkillLearnedData(
                skill_name=skill_name,
                pattern=pattern,
                scope=scope,
                source=source,  # type: ignore[arg-type]
            ),
        )
        self._write(evt)
        return evt

    def emit_prompt_requested(
        self,
        *,
        kind: str = "user_turn",
        preview: str | None = None,
        parent: str | None = None,
    ) -> PromptRequested:
        evt = PromptRequested(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=PromptRequestedData(
                kind=kind,  # type: ignore[arg-type]
                preview=preview,
            ),
        )
        self._write(evt)
        return evt

    def emit_prompt_cancelled(
        self,
        *,
        reason: str,
        detail: str | None = None,
        parent: str | None = None,
    ) -> PromptCancelled:
        evt = PromptCancelled(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=PromptCancelledData(
                reason=reason,  # type: ignore[arg-type]
                detail=detail,
            ),
        )
        self._write(evt)
        return evt

    def emit_checkpoint_saved(
        self,
        *,
        thread: str,
        run_id: str | None = None,
        label: str | None = None,
        parent: str | None = None,
    ) -> CheckpointSaved:
        """Emit after a LangGraph checkpoint is successfully persisted."""
        evt = CheckpointSaved(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=CheckpointSavedData(thread=thread, run_id=run_id, label=label),
        )
        self._write(evt)
        return evt

    def emit_checkpoint_restored(
        self,
        *,
        thread: str,
        resumed_from_run_id: str | None = None,
        parent: str | None = None,
    ) -> CheckpointRestored:
        """Emit when the runtime resumes execution from an existing checkpoint."""
        evt = CheckpointRestored(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=CheckpointRestoredData(thread=thread, resumed_from_run_id=resumed_from_run_id),
        )
        self._write(evt)
        return evt

    def emit_feedback_scored(
        self,
        *,
        run_id: str,
        rating: str,
        comment: str = "",
        correct: str = "",
        metadata: dict[str, Any] | None = None,
        parent: str | None = None,
    ) -> FeedbackScored:
        """Emit when a user submits feedback for a completed turn."""
        evt = FeedbackScored(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=FeedbackScoredData(
                run_id=run_id,
                rating=rating,
                comment=comment,
                correct=correct,
                metadata=metadata,
            ),
        )
        self._write(evt)
        return evt

    def emit_memory_session_write(
        self,
        *,
        thread: str,
        run_id: str | None = None,
        query_preview: str | None = None,
        output_preview: str | None = None,
        turn_count: int | None = None,
        parent: str | None = None,
    ) -> MemorySessionWrite:
        """Emit after a turn is persisted into session (short-term) memory."""
        evt = MemorySessionWrite(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MemorySessionWriteData(
                thread=thread,
                run_id=run_id,
                query_preview=query_preview,
                output_preview=output_preview,
                turn_count=turn_count,
            ),
        )
        self._write(evt)
        return evt

    def emit_memory_session_cleared(self, *, thread: str, parent: str | None = None) -> MemorySessionCleared:
        """Emit after short-term session memory for *thread* was cleared."""
        evt = MemorySessionCleared(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MemorySessionClearedData(thread=thread),
        )
        self._write(evt)
        return evt

    def emit_memory_session_turn_popped(
        self,
        *,
        thread: str,
        remaining_turns: int,
        parent: str | None = None,
    ) -> MemorySessionTurnPopped:
        """Emit after the last short-term session-memory turn was removed (undo)."""
        evt = MemorySessionTurnPopped(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MemorySessionTurnPoppedData(thread=thread, remaining_turns=remaining_turns),
        )
        self._write(evt)
        return evt

    def emit_memory_lt_recall(
        self,
        *,
        namespace: str | None = None,
        query_preview: str | None = None,
        hits: int = 0,
        injected_chars: int = 0,
        parent: str | None = None,
    ) -> MemoryLtRecall:
        """Emit when long-term memory is searched to build the query context."""
        evt = MemoryLtRecall(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MemoryLtRecallData(
                namespace=namespace,
                query_preview=query_preview,
                hits=hits,
                injected_chars=injected_chars,
            ),
        )
        self._write(evt)
        return evt

    def emit_memory_lt_store(
        self,
        *,
        namespace: str | None = None,
        key: str | None = None,
        content_preview: str | None = None,
        parent: str | None = None,
    ) -> MemoryLtStore:
        """Emit when a fact is persisted into long-term memory."""
        evt = MemoryLtStore(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MemoryLtStoreData(
                namespace=namespace,
                key=key,
                content_preview=content_preview,
            ),
        )
        self._write(evt)
        return evt

    def emit_metric_tokens(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int | None = None,
        model: str | None = None,
        phase: str | None = None,
        worker_id: str | None = None,
        parent: str | None = None,
    ) -> MetricTokens:
        """Per-LLM-call token usage delta. Frontends sum across the session for the sidebar rollup."""
        evt = MetricTokens(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MetricTokensData(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                phase=phase,
                worker_id=worker_id,
            ),
        )
        self._write(evt)
        return evt

    def emit_metric_cost(
        self,
        *,
        cost: float,
        currency: str = "USD",
        model: str | None = None,
        phase: str | None = None,
        worker_id: str | None = None,
        parent: str | None = None,
    ) -> MetricCost:
        """Per-billable-unit cost delta. Currency defaults to USD."""
        evt = MetricCost(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MetricCostData(
                cost=cost,
                currency=currency,
                model=model,
                phase=phase,
                worker_id=worker_id,
            ),
        )
        self._write(evt)
        return evt

    def emit_metric_budget_approaching(
        self,
        *,
        dimension: Literal["tokens", "cost_usd"],
        used: float,
        limit: float,
        ratio: float,
        parent: str | None = None,
    ) -> MetricBudgetApproaching:
        evt = MetricBudgetApproaching(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MetricBudgetApproachingData(
                dimension=dimension,
                used=used,
                limit=limit,
                ratio=ratio,
            ),
        )
        self._write(evt)
        return evt

    def emit_metric_budget_exhausted(
        self,
        *,
        dimension: Literal["tokens", "cost_usd"],
        used: float,
        limit: float,
        parent: str | None = None,
    ) -> MetricBudgetExhausted:
        evt = MetricBudgetExhausted(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MetricBudgetExhaustedData(
                dimension=dimension,
                used=used,
                limit=limit,
            ),
        )
        self._write(evt)
        return evt

    def emit_runtime_ready(
        self,
        *,
        agent_name: str | None = None,
        cli_tools_enabled: bool | None = None,
        cli_tools_count: int | None = None,
        parent: str | None = None,
    ) -> RuntimeReady:
        evt = RuntimeReady(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeReadyData(
                agent_name=agent_name,
                cli_tools_enabled=cli_tools_enabled,
                cli_tools_count=cli_tools_count,
            ),
        )
        self._write(evt)
        return evt

    def emit_runtime_config(
        self,
        *,
        model_id: str | None = None,
        tool_names: list[str] | None = None,
        capabilities: list[str] | None = None,
        cli_tools_enabled: bool | None = None,
        cli_tools_count: int | None = None,
        parent: str | None = None,
    ) -> RuntimeConfig:
        caps = list(capabilities) if capabilities is not None else list(self._capabilities)
        evt = RuntimeConfig(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeConfigData(
                model_id=model_id,
                tool_names=list(tool_names or []),
                capabilities=caps,
                cli_tools_enabled=cli_tools_enabled,
                cli_tools_count=cli_tools_count,
            ),
        )
        self._write(evt)
        return evt

    def emit_runtime_pong(self, *, ping_id: str | None = None, parent: str | None = None) -> RuntimePong:
        evt = RuntimePong(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimePongData(ping_id=ping_id),
        )
        self._write(evt)
        return evt

    def emit_runtime_schema(self, *, json_schema: dict[str, Any], parent: str | None = None) -> RuntimeSchemaPayload:
        evt = RuntimeSchemaPayload(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeSchemaPayloadData(json_schema=json_schema),
        )
        self._write(evt)
        return evt

    def emit_runtime_tools(
        self,
        *,
        tools: list[tuple[str, str | None]],
        parent: str | None = None,
    ) -> RuntimeToolsPayload:
        entries = [RuntimeToolEntry(name=n, description=d) for n, d in tools]
        evt = RuntimeToolsPayload(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeToolsPayloadData(tools=entries),
        )
        self._write(evt)
        return evt

    def emit_runtime_providers(
        self,
        *,
        providers: list[dict[str, Any]],
        parent: str | None = None,
    ) -> RuntimeProvidersPayload:
        rows = [
            RuntimeProviderEntry(
                slug=str(r["slug"]),
                label=str(r["label"]),
                default_model=str(r["default_model"]),
                primary_env_key=r.get("primary_env_key"),
            )
            for r in providers
        ]
        evt = RuntimeProvidersPayload(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeProvidersPayloadData(providers=rows),
        )
        self._write(evt)
        return evt

    def emit_runtime_sessions(self, *, sessions: list[str], parent: str | None = None) -> RuntimeSessionsPayload:
        evt = RuntimeSessionsPayload(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeSessionsPayloadData(sessions=list(sessions)),
        )
        self._write(evt)
        return evt

    def emit_runtime_session_created(self, *, session_id: str, parent: str | None = None) -> RuntimeSessionCreated:
        evt = RuntimeSessionCreated(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeSessionCreatedData(session_id=session_id),
        )
        self._write(evt)
        return evt

    def emit_runtime_session_renamed(
        self, *, from_session_id: str, to_session_id: str, parent: str | None = None
    ) -> RuntimeSessionRenamed:
        evt = RuntimeSessionRenamed(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeSessionRenamedData(from_session_id=from_session_id, to_session_id=to_session_id),
        )
        self._write(evt)
        return evt

    def emit_runtime_file_staged(
        self,
        *,
        path: str,
        nbytes: int,
        thread: str | None = None,
        parent: str | None = None,
    ) -> RuntimeFileStaged:
        evt = RuntimeFileStaged(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeFileStagedData(path=path, bytes=nbytes, thread=thread),
        )
        self._write(evt)
        return evt

    def emit_runtime_tool_result(
        self,
        *,
        ok: bool,
        result: Any | None = None,
        error: str | None = None,
        parent: str | None = None,
    ) -> RuntimeToolInvokeResult:
        evt = RuntimeToolInvokeResult(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeToolInvokeResultData(ok=ok, result=result, error=error),
        )
        self._write(evt)
        return evt

    def emit_runtime_config_applied(
        self,
        *,
        model_id: str | None = None,
        cli_tools_enabled: bool | None = None,
        cli_tools_count: int | None = None,
        parent: str | None = None,
    ) -> RuntimeConfigApplied:
        evt = RuntimeConfigApplied(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=RuntimeConfigAppliedData(
                model_id=model_id,
                cli_tools_enabled=cli_tools_enabled,
                cli_tools_count=cli_tools_count,
            ),
        )
        self._write(evt)
        return evt

    def emit_todos_updated(self, *, items: list[dict[str, Any]], parent: str | None = None) -> TodosUpdated:
        evt = TodosUpdated(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=TodosUpdatedData(items=list(items)),
        )
        self._write(evt)
        return evt

    def emit_session_heartbeat(self, *, uptime_ms: int | None = None, parent: str | None = None) -> SessionHeartbeat:
        evt = SessionHeartbeat(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=SessionHeartbeatData(uptime_ms=uptime_ms),
        )
        self._write(evt)
        return evt

    def emit_agent_busy(self, *, thread: str | None = None, parent: str | None = None) -> AgentBusy:
        evt = AgentBusy(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=AgentBusyData(thread=thread or self._thread),
        )
        self._write(evt)
        return evt

    def emit_agent_idle(self, *, thread: str | None = None, parent: str | None = None) -> AgentIdle:
        evt = AgentIdle(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=AgentIdleData(thread=thread or self._thread),
        )
        self._write(evt)
        return evt

    def emit_message_tool(
        self,
        *,
        tool_name: str,
        phase: Literal["start", "progress", "end"] = "progress",
        detail: str | None = None,
        call_id: str | None = None,
        parent: str | None = None,
    ) -> MessageTool:
        evt = MessageTool(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=MessageToolData(tool_name=tool_name, phase=phase, detail=detail, call_id=call_id),
        )
        self._write(evt)
        return evt

    def emit_stream_heartbeat(
        self,
        *,
        thread: str | None = None,
        chars_since_last: int | None = None,
        parent: str | None = None,
    ) -> StreamHeartbeat:
        evt = StreamHeartbeat(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=StreamHeartbeatData(thread=thread or self._thread, chars_since_last=chars_since_last),
        )
        self._write(evt)
        return evt

    def emit_error(
        self,
        *,
        severity: ErrorSeverity,
        message: str,
        error_class: str | None = None,
        stage: str | None = None,
        retryable: bool = False,
        parent: str | None = None,
    ) -> ErrorTransient | ErrorFatal:
        """Emit ``error.transient`` or ``error.fatal`` based on *severity*.

        ``fatal`` precedes a ``session.closed(reason="error")``; ``transient`` is informational
        (e.g. a tool retry, a rate-limit backoff) and does not end the session.
        """
        data = ErrorData(
            severity=severity,
            message=message,
            error_class=error_class,
            stage=stage,
            retryable=retryable,
        )
        cls = ErrorFatal if severity == "fatal" else ErrorTransient
        evt = cls(
            session=self._session,
            thread=self._thread,
            seq=self._next_seq(),
            parent=parent,
            data=data,
        )
        self._write(evt)
        return evt

    # ── introspection ────────────────────────────────────────────────────────

    @property
    def session_id(self) -> str:
        return self._session

    @property
    def thread_id(self) -> str:
        return self._thread

    @property
    def seq(self) -> int:
        """Last emitted sequence number (``0`` before any emission)."""
        return self._shared_seq.value

    @property
    def is_open(self) -> bool:
        return self._opened and not self._closed

    def fork_for_thread(self, thread: str) -> SessionEmitter:
        """Return a sibling emitter bound to *thread* that shares this session's seq counter
        and writer lock.

        Use this inside the AGP serve loop when a ``command.invoke`` starts a new invocation
        on a different ``thread_id`` so concurrent invocations each have their own emitter
        without racing on ``_thread`` or producing duplicate ``seq`` numbers.

        The forked emitter is *not* opened/closed automatically — the caller is responsible
        for its lifecycle (typically the bridge does this).
        """
        child = SessionEmitter(
            session=self._session,
            thread=thread,
            writer=self._writer,
            capabilities=list(self._capabilities),
            on_emit=self._on_emit,
            store=self._store,
            _shared_seq=self._shared_seq,
            _write_lock=self._write_lock,
            _sub_filter=self._sub_filter,
        )
        # Mark as already open so the child doesn't re-emit session.opened.
        child._opened = True
        if getattr(self, "budget_tracker", None) is not None:
            child.budget_tracker = self.budget_tracker  # type: ignore[attr-defined]
        return child

    # ── subscription filter (command.subscribe / unsubscribe) ─────────────────

    def set_subscription_prefixes(self, prefixes: list[str] | None) -> None:
        """Restrict outbound NDJSON to events whose ``type`` matches a prefix (plus passthrough).

        ``None`` or an empty list clears the filter (full stream). Forked emitters share state.
        """
        if prefixes:
            self._sub_filter.prefixes = list(prefixes)
        else:
            self._sub_filter.prefixes = None

    def clear_subscription(self) -> None:
        """Clear any active subscription filter (same as ``set_subscription_prefixes(None)``)."""
        self._sub_filter.prefixes = None

    def _subscription_allows_wire(self, typ: str) -> bool:
        prefs = self._sub_filter.prefixes
        if prefs is None:
            return True
        if typ.startswith(("session.", "error.", "runtime.", "prompt.", "hitl.")):
            return True
        return any(typ.startswith(p) for p in prefs)

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _next_seq(self) -> int:
        return self._shared_seq.next()

    def _write(self, evt: Envelope) -> None:
        typ = str(getattr(evt, "type", ""))
        wire_ok = self._subscription_allows_wire(typ)
        line = evt.model_dump_json(by_alias=True, exclude_none=True)
        if self._writer is not None and wire_ok:
            with self._write_lock:
                self._writer.write(line + "\n")
                self._writer.flush()
        if self._on_emit is not None:
            try:
                self._on_emit(evt)
            except Exception:
                # ``on_emit`` is observation-only; failures must not affect the wire.
                pass
        if self._store is not None:
            try:
                d = event_to_dict(evt)
                try:
                    loop = asyncio.get_running_loop()
                    t = loop.create_task(self._store.append(self._session, d))
                    t.add_done_callback(_store_append_done)
                except RuntimeError:
                    # No running event loop (e.g. synchronous test context). Skip store persistence
                    # rather than raising — the synchronous emitter is not async-safe.
                    pass
            except Exception:
                pass


def event_to_dict(evt: Envelope) -> dict[str, Any]:
    """Round-trip helper: dump an event to its on-the-wire dict form (parsed JSON)."""
    return evt.model_dump(mode="json", by_alias=True, exclude_none=True)


class AsyncSessionEmitter(SessionEmitter):
    """``SessionEmitter`` with an async-safe write path backed by an ``asyncio.Queue``.

    Drop-in replacement for use in WebSocket / async transport contexts where blocking
    ``writer.write()`` + ``flush()`` on the event-loop thread is undesirable.

    Usage::

        emitter = AsyncSessionEmitter(session=..., thread=..., writer=ws_send_callable)
        async with emitter:          # starts drain task
            emitter.open()
            ...                      # emit_* calls are non-blocking (enqueue only)
        # context exit drains the queue and calls writer(None) as an EOF sentinel

    The *writer* here may be any async callable that accepts a JSON string — e.g. a
    WebSocket send coroutine.  For backward compatibility with sync writers (``IO[str]``)
    the drain task calls it via ``loop.run_in_executor`` when it is not a coroutine function.
    """

    def __init__(
        self,
        *,
        session: str,
        thread: str,
        writer: Any = None,
        capabilities: list[str] | None = None,
        on_emit: Callable[[Envelope], None] | None = None,
        store: Any | None = None,
        queue_maxsize: int = 0,
        _shared_seq: _SharedSeq | None = None,
        _write_lock: threading.Lock | None = None,
        _sub_filter: _SubscriptionFilter | None = None,
    ) -> None:
        # Do NOT pass writer to parent — we manage writes ourselves via the queue.
        super().__init__(
            session=session,
            thread=thread,
            writer=None,
            capabilities=capabilities,
            on_emit=on_emit,
            store=store,
            _shared_seq=_shared_seq,
            _write_lock=_write_lock,
            _sub_filter=_sub_filter,
        )
        # Parent __init__ defaults to sys.stdout; override to None since AsyncSessionEmitter
        # routes all writes through its internal queue — the async_writer is the real target.
        self._writer = None
        self._async_writer = writer
        self._queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=queue_maxsize)
        self._drain_task: asyncio.Task[None] | None = None

    # ── async context manager ────────────────────────────────────────────────

    async def __aenter__(self) -> AsyncSessionEmitter:
        await self.start()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.stop()

    async def start(self) -> None:
        """Start the background drain task."""
        if self._drain_task is not None and not self._drain_task.done():
            return
        self._drain_task = asyncio.create_task(self._drain(), name="agp-async-emitter-drain")

    async def stop(self) -> None:
        """Flush the queue and stop the drain task."""
        await self._queue.put(None)  # sentinel
        if self._drain_task is not None:
            try:
                await self._drain_task
            except Exception:
                pass
            self._drain_task = None

    # ── override _write to enqueue instead of block ─────────────────────────

    def _write(self, evt: Envelope) -> None:
        typ = str(getattr(evt, "type", ""))
        wire_ok = self._subscription_allows_wire(typ)
        line = evt.model_dump_json(by_alias=True, exclude_none=True)
        if wire_ok:
            self._queue.put_nowait(line)
        if self._on_emit is not None:
            try:
                self._on_emit(evt)
            except Exception:
                pass
        if self._store is not None:
            try:
                d = event_to_dict(evt)
                t = asyncio.get_running_loop().create_task(self._store.append(self._session, d))
                t.add_done_callback(_store_append_done)
            except Exception:
                pass

    # ── drain loop ───────────────────────────────────────────────────────────

    async def _drain(self) -> None:
        import inspect

        loop = asyncio.get_running_loop()
        writer = self._async_writer
        while True:
            item = await self._queue.get()
            if item is None:
                break
            if writer is None:
                continue
            try:
                if inspect.iscoroutinefunction(writer):
                    await writer(item + "\n")
                else:
                    await loop.run_in_executor(None, writer, item + "\n")
            except Exception:
                pass

    def fork_for_thread(self, thread: str) -> AsyncSessionEmitter:
        """Fork an ``AsyncSessionEmitter`` sibling sharing the same drain queue and seq counter."""
        child = AsyncSessionEmitter(
            session=self._session,
            thread=thread,
            writer=self._async_writer,
            capabilities=list(self._capabilities),
            on_emit=self._on_emit,
            store=self._store,
            _shared_seq=self._shared_seq,
            _write_lock=self._write_lock,
            _sub_filter=self._sub_filter,
        )
        # Share the same queue so a single drain task handles all forked emitters.
        child._queue = self._queue
        child._drain_task = self._drain_task
        child._opened = True
        if getattr(self, "budget_tracker", None) is not None:
            child.budget_tracker = self.budget_tracker  # type: ignore[attr-defined]
        return child


__all__ = ["AsyncSessionEmitter", "SessionEmitter", "WriterLike", "event_to_dict"]
