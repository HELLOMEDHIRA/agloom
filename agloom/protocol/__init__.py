"""Agloom Protocol (AGP) — wire format between the Python runtime and any frontend.

AGP is an event-driven, JSON-based, transport-agnostic contract. The Python runtime emits
events; clients (agloom CLI, web workspace, IDE integrations, replay tools) consume them.

**Surface**:

- :class:`Envelope` — common fields every event carries (``v``, ``id``, ``ts``, ``session``,
  ``thread``, ``seq``, ``type``, ``data``).
- Concrete event types — see :mod:`agloom.protocol.events`.
- :data:`Event` — the discriminated union; parse arbitrary AGP events with
  :data:`event_adapter`.
- :class:`SessionEmitter` — typed NDJSON writer (one event per line, flushed per emit).
- :class:`AsyncSessionEmitter` — non-blocking async writer backed by an asyncio queue.
- Inbound commands — see :mod:`agloom.protocol.commands`; parse with :data:`command_adapter`.
- :mod:`agloom.protocol.store` — :class:`MemoryEventStore` and :class:`SqliteEventStore`
  for replay/resume.

See ``agloom/docs/protocol/agp.md`` for the full specification.
"""

from __future__ import annotations

from typing import Any

from .commands import (
    Command,
    CommandAttachFile,
    CommandAttachFileData,
    CommandCancel,
    CommandCancelData,
    CommandConfigSet,
    CommandConfigSetData,
    CommandFeedback,
    CommandFeedbackData,
    CommandHarnessGit,
    CommandHarnessGitData,
    CommandHITLRespond,
    CommandHITLRespondData,
    CommandInvoke,
    CommandInvokeData,
    CommandMemoryClear,
    CommandMemoryClearData,
    CommandMemoryPopLastTurn,
    CommandMemoryPopLastTurnData,
    CommandPing,
    CommandPingData,
    CommandPlanPreview,
    CommandPlanPreviewData,
    CommandProvidersList,
    CommandProvidersListData,
    CommandRuntimeShutdown,
    CommandRuntimeShutdownData,
    CommandSchemaRequest,
    CommandSchemaRequestData,
    CommandSessionCreate,
    CommandSessionCreateData,
    CommandSessionDelete,
    CommandSessionDeleteData,
    CommandSessionList,
    CommandSessionListData,
    CommandSessionRename,
    CommandSessionRenameData,
    CommandSessionResume,
    CommandSessionResumeData,
    CommandSnapshotRequest,
    CommandSnapshotRequestData,
    CommandSubscribe,
    CommandSubscribeData,
    CommandToolInvoke,
    CommandToolInvokeData,
    CommandToolList,
    CommandToolListData,
    CommandUnsubscribe,
    CommandUnsubscribeData,
    CommandWorkerAssign,
    CommandWorkerAssignData,
    InvokeAttachment,
    command_adapter,
)


def __getattr__(name: str) -> Any:
    """Lazy-load heavy protocol submodules (use ``importlib.import_module`` to avoid recursion)."""
    import importlib

    if name == "__version__":
        _envelope = importlib.import_module(f"{__name__}.envelope")
        v = _envelope.PROTOCOL_MODULE_VERSION
        globals()["__version__"] = v
        return v

    _envelope_names = frozenset(
        {"PROTOCOL_MODULE_VERSION", "PROTOCOL_VERSION", "Envelope", "new_event_id", "now_utc"}
    )
    if name in _envelope_names:
        _envelope = importlib.import_module(f"{__name__}.envelope")
        obj = getattr(_envelope, name)
        globals()[name] = obj
        return obj

    _emitter_names = frozenset({"AsyncSessionEmitter", "SessionEmitter", "WriterLike", "event_to_dict"})
    if name in _emitter_names:
        _emitter = importlib.import_module(f"{__name__}.emitter")
        obj = getattr(_emitter, name)
        globals()[name] = obj
        return obj

    _schema_names = frozenset({"build_schema", "write_schema"})
    if name in _schema_names:
        _schema = importlib.import_module(f"{__name__}.schema")
        obj = getattr(_schema, name)
        globals()[name] = obj
        return obj

    _store_names = frozenset({"EventStore", "MemoryEventStore", "SqliteEventStore"})
    if name in _store_names:
        _store = importlib.import_module(f"{__name__}.store")
        obj = getattr(_store, name)
        globals()[name] = obj
        return obj

    _events = importlib.import_module(f"{__name__}.events")
    if hasattr(_events, name):
        obj = getattr(_events, name)
        globals()[name] = obj
        return obj

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)

__all__ = [
    # ── envelope ──
    "PROTOCOL_MODULE_VERSION",
    "PROTOCOL_VERSION",
    "Envelope",
    "new_event_id",
    "now_utc",
    # ── emitter ──
    "AsyncSessionEmitter",
    "SessionEmitter",
    "WriterLike",
    "event_to_dict",
    # ── schema ──
    "build_schema",
    "write_schema",
    # ── store ──
    "EventStore",
    "MemoryEventStore",
    "SqliteEventStore",
    # ── commands ──
    "Command",
    "CommandAttachFile",
    "CommandAttachFileData",
    "CommandCancel",
    "CommandCancelData",
    "CommandConfigSet",
    "CommandConfigSetData",
    "CommandFeedback",
    "CommandFeedbackData",
    "CommandHarnessGit",
    "CommandHarnessGitData",
    "CommandHITLRespond",
    "CommandHITLRespondData",
    "CommandInvoke",
    "CommandInvokeData",
    "InvokeAttachment",
    "CommandMemoryClear",
    "CommandMemoryClearData",
    "CommandMemoryPopLastTurn",
    "CommandMemoryPopLastTurnData",
    "CommandPing",
    "CommandPingData",
    "CommandPlanPreview",
    "CommandPlanPreviewData",
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
    # ── events ──
    "AgentBusy",
    "AgentBusyData",
    "AgentIdle",
    "AgentIdleData",
    "CheckpointRestored",
    "CheckpointRestoredData",
    "CheckpointSaved",
    "CheckpointSavedData",
    "ErrorData",
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
    "MemorySessionCleared",
    "MemorySessionClearedData",
    "MemorySessionTurnPopped",
    "MemorySessionTurnPoppedData",
    "MemorySessionWrite",
    "MemorySessionWriteData",
    "MessageAssistant",
    "MessageAssistantData",
    "MessageTool",
    "MessageToolData",
    "MessageUser",
    "MessageUserData",
    "MetricBudgetApproaching",
    "MetricBudgetApproachingData",
    "MetricBudgetExhausted",
    "MetricBudgetExhaustedData",
    "MetricCost",
    "MetricCostData",
    "MetricTokens",
    "MetricTokensData",
    "PatternClassified",
    "PatternClassifiedData",
    "PlanPreview",
    "PlanPreviewData",
    "PromptCancelled",
    "PromptCancelledData",
    "PromptCancelledReason",
    "PromptRequested",
    "PromptRequestedData",
    "PromptRequestedKind",
    "RuntimeConfig",
    "RuntimeConfigApplied",
    "RuntimeConfigAppliedData",
    "RuntimeConfigData",
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
    "RuntimeFileStaged",
    "RuntimeFileStagedData",
    "RuntimeSessionsPayload",
    "RuntimeSessionsPayloadData",
    "RuntimeToolEntry",
    "RuntimeToolInvokeResult",
    "RuntimeToolInvokeResultData",
    "RuntimeToolsPayload",
    "RuntimeToolsPayloadData",
    "SessionCloseReason",
    "SessionClosed",
    "SessionClosedData",
    "SessionHeartbeat",
    "SessionHeartbeatData",
    "SessionOpened",
    "SessionOpenedData",
    "SessionResumed",
    "SessionResumedData",
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
    "ProgressStep",
    "ProgressStepData",
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
    "WorkerHalted",
    "WorkerHaltedData",
    "WorkerSpawned",
    "WorkerSpawnedData",
    "event_adapter",
    "__version__",
]
