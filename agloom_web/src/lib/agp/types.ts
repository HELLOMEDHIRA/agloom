/**
 * TypeScript mirror of the Pydantic AGP event and command models.
 *
 * Every interface here maps 1-to-1 to the Python Pydantic models in
 * `agloom/protocol/events.py` and `agloom/protocol/commands.py`.
 *
 * Duplicated at agloom_cli/src/types/agp.ts and agloom_web/src/lib/agp/types.ts — keep both files identical.
 */

// ── Envelope (base fields present on every event) ────────────────────────────

export interface Envelope {
  /** AGP protocol version — always "1" for AGP v1 */
  v: '1'
  /** AGP session identifier */
  session: string
  /** Monotonically increasing per-session sequence number */
  seq: number
  /** ISO-8601 timestamp */
  ts: string
  /** Unique event identifier (UUID4 hex) */
  id: string
  /** LangGraph thread id */
  thread?: string
  /** Parent event id — links child events to the event that spawned them */
  parent?: string
  /** LangSmith trace id for distributed tracing correlation */
  trace?: string
}

// ── session.* ────────────────────────────────────────────────────────────────

export interface SessionOpenedEvent extends Envelope {
  type: 'session.opened'
  data: { runtime_version: string; protocol_version: string; capabilities: string[] }
}

export interface SessionResumedEvent extends Envelope {
  type: 'session.resumed'
  data: {
    runtime_version: string
    protocol_version: string
    capabilities: string[]
    resumed_from_thread?: string
    replayed_from_seq?: number
  }
}

export interface SessionClosedEvent extends Envelope {
  type: 'session.closed'
  data: {
    reason: 'completed' | 'user_aborted' | 'error' | 'shutdown' | string
    duration_ms?: number
    error?: string
  }
}

// ── pattern.* ────────────────────────────────────────────────────────────────

export interface PatternClassifiedEvent extends Envelope {
  type: 'pattern.classified'
  data: { pattern: string; complexity?: number; confidence?: number; reason?: string }
}

// ── thinking.* ───────────────────────────────────────────────────────────────

export interface ThinkingStepEvent extends Envelope {
  type: 'thinking.step'
  data: { step: string; label?: string; detail?: string; elapsed_ms?: number }
}

// ── token.* ──────────────────────────────────────────────────────────────────

export interface TokenDeltaEvent extends Envelope {
  type: 'token.delta'
  /** `text` is the incremental token text. `role` defaults to "assistant". */
  data: { text: string; role?: 'assistant' | 'tool'; message_id?: string }
}

// ── message.* ────────────────────────────────────────────────────────────────

export interface MessageUserEvent extends Envelope {
  type: 'message.user'
  data: { content: string; message_id?: string }
}

export interface MessageAssistantEvent extends Envelope {
  type: 'message.assistant'
  data: { content: string; message_id?: string; run_id?: string; pattern?: string }
}

// ── tool.* ───────────────────────────────────────────────────────────────────

export interface ToolCallStartEvent extends Envelope {
  type: 'tool.call.start'
  data: {
    tool: string
    tool_call_id: string
    args: Record<string, unknown>
    worker?: string
  }
}

export interface ToolCallResultEvent extends Envelope {
  type: 'tool.call.result'
  data: {
    tool: string
    tool_call_id: string
    output_preview?: string
    output_bytes?: number
    duration_ms?: number
    truncated?: boolean
  }
}

export interface ToolCallErrorEvent extends Envelope {
  type: 'tool.call.error'
  data: {
    tool: string
    tool_call_id: string
    error: string
    error_class?: string
    duration_ms?: number
  }
}

// ── hitl.* ───────────────────────────────────────────────────────────────────

export interface HITLRequestEvent extends Envelope {
  type: 'hitl.request'
  data: {
    request_id: string
    kind: 'tool_approval' | 'pattern_approval' | 'worker_approval' | 'react_recovery' | 'clarification' | string
    detail?: string
    options: string[]
    default?: string
    timeout_ms?: number
    agent_name?: string
    tool?: string
    tool_call_id?: string
    args?: Record<string, unknown>
    worker?: string
    pattern?: string
    question?: string
  }
}

export interface HITLDecisionData {
  request_id: string
  decision: 'accept' | 'reject' | 'allowlist' | 'retry' | 'stop' | 'timeout' | 'cancelled' | string
  actor?: 'user' | 'auto' | 'timeout'
  text?: string   // free-text answer for clarification kind
  detail?: string
}

export interface HITLGrantedEvent extends Envelope {
  type: 'hitl.granted'
  data: HITLDecisionData
}

export interface HITLDeniedEvent extends Envelope {
  type: 'hitl.denied'
  data: HITLDecisionData
}

export interface HITLAllowlistedEvent extends Envelope {
  type: 'hitl.allowlisted'
  data: HITLDecisionData
}

// ── worker.* ─────────────────────────────────────────────────────────────────

export interface WorkerSpawnedEvent extends Envelope {
  type: 'worker.spawned'
  data: { worker_id: string; name?: string; pattern?: string; task?: string; parent_worker_id?: string }
}

export interface WorkerCompletedEvent extends Envelope {
  type: 'worker.completed'
  data: { worker_id: string; output_preview?: string; output_bytes?: number; duration_ms?: number; truncated?: boolean }
}

export interface WorkerFailedEvent extends Envelope {
  type: 'worker.failed'
  data: { worker_id: string; error: string; error_class?: string; duration_ms?: number }
}

// ── graph.* ──────────────────────────────────────────────────────────────────

export interface GraphNodeEnterEvent extends Envelope {
  type: 'graph.node.enter'
  data: { node: string; pattern?: string; input_preview?: string }
}

export interface GraphNodeExitEvent extends Envelope {
  type: 'graph.node.exit'
  data: { node: string; pattern?: string; duration_ms?: number; output_preview?: string; error?: string }
}

// ── memory.* ─────────────────────────────────────────────────────────────────

export interface MemoryLtRecallEvent extends Envelope {
  type: 'memory.lt.recall'
  data: { namespace?: string; query_preview?: string; hits: number; injected_chars: number }
}

export interface MemorySessionWriteEvent extends Envelope {
  type: 'memory.session.write'
  data: { thread: string; run_id?: string; query_preview?: string; output_preview?: string; turn_count?: number }
}

export interface MemoryLtStoreEvent extends Envelope {
  type: 'memory.lt.store'
  data: { namespace?: string; key?: string; content_preview?: string }
}

// ── checkpoint.* ─────────────────────────────────────────────────────────────

export interface CheckpointSavedEvent extends Envelope {
  type: 'checkpoint.saved'
  data: { thread: string; run_id?: string; label?: string }
}

export interface CheckpointRestoredEvent extends Envelope {
  type: 'checkpoint.restored'
  data: { thread: string; resumed_from_run_id?: string }
}

// ── feedback.* ───────────────────────────────────────────────────────────────

export interface FeedbackScoredEvent extends Envelope {
  type: 'feedback.scored'
  /** `rating` is a string token: "positive" / "negative" / "neutral" or numeric string */
  data: { run_id: string; rating: string; comment?: string; correct?: string; metadata?: Record<string, unknown> }
}

// ── metric.* ─────────────────────────────────────────────────────────────────

export interface MetricTokensEvent extends Envelope {
  type: 'metric.tokens'
  data: {
    model?: string
    input_tokens: number
    output_tokens: number
    total_tokens?: number
    phase?: string
    worker_id?: string
  }
}

export interface MetricCostEvent extends Envelope {
  type: 'metric.cost'
  data: { cost: number; currency?: string; model?: string; phase?: string; worker_id?: string }
}

// ── error.* ──────────────────────────────────────────────────────────────────

export interface ErrorEventData {
  severity: 'transient' | 'fatal'
  message: string
  error_class?: string
  stage?: string
  retryable?: boolean
}

export interface ErrorTransientEvent extends Envelope {
  type: 'error.transient'
  data: ErrorEventData
}

export interface ErrorFatalEvent extends Envelope {
  type: 'error.fatal'
  data: ErrorEventData
}

// ── Discriminated union ───────────────────────────────────────────────────────

export type AGPEvent =
  | SessionOpenedEvent
  | SessionResumedEvent
  | SessionClosedEvent
  | PatternClassifiedEvent
  | ThinkingStepEvent
  | TokenDeltaEvent
  | MessageUserEvent
  | MessageAssistantEvent
  | ToolCallStartEvent
  | ToolCallResultEvent
  | ToolCallErrorEvent
  | HITLRequestEvent
  | HITLGrantedEvent
  | HITLDeniedEvent
  | HITLAllowlistedEvent
  | WorkerSpawnedEvent
  | WorkerCompletedEvent
  | WorkerFailedEvent
  | GraphNodeEnterEvent
  | GraphNodeExitEvent
  | MemoryLtRecallEvent
  | MemorySessionWriteEvent
  | MemoryLtStoreEvent
  | CheckpointSavedEvent
  | CheckpointRestoredEvent
  | FeedbackScoredEvent
  | MetricTokensEvent
  | MetricCostEvent
  | ErrorTransientEvent
  | ErrorFatalEvent

// ── Inbound commands (CLI / web → Python runtime) ────────────────────────────

export interface CommandInvoke {
  type: 'command.invoke'
  data: { prompt: string; thread?: string }
}

export interface CommandCancel {
  type: 'command.cancel'
  data: { thread?: string }
}

export interface CommandHITLRespond {
  type: 'command.hitl.respond'
  data: { request_id: string; decision: string; text?: string }
}

export interface CommandRuntimeShutdown {
  type: 'command.runtime.shutdown'
}

export interface CommandFeedback {
  type: 'command.feedback'
  /** `rating` must be a string token — e.g. "positive", "negative", "neutral" or a numeric string like "5" */
  data: { run_id: string; rating: string; comment?: string; correct?: string; metadata?: Record<string, unknown> }
}

export interface CommandSnapshotRequest {
  type: 'command.snapshot.request'
  data?: { thread?: string; label?: string }
}

export type AGPCommand =
  | CommandInvoke
  | CommandCancel
  | CommandHITLRespond
  | CommandRuntimeShutdown
  | CommandFeedback
  | CommandSnapshotRequest

// ── Utility types ──────────────────────────────────────────────────────────────

export type ConnectionStatus = 'connecting' | 'open' | 'closed' | 'error'
