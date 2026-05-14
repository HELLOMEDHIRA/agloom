/** TypeScript mirror of the Pydantic AGP event and command models.
 * Every interface here maps 1-to-1 to the Python Pydantic models in `agloom/protocol/events.py` and `agloom/protocol/commands.py`. Duplicated at agloom_cli/src/types/agp.ts and agloom_web/src/lib/agp/types.ts — keep both files identical. Zod wire validation lives in ``agpWireParse.ts`` (duplicate at ``agloom_web/src/lib/agp/agpWireParse.ts``).
 */

import { parseInboundAGPEventJSONWire } from './agpWireParse.js'

// Envelope (base fields present on every event)

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

// session.*

export interface SessionOpenedEvent extends Envelope {
  type: 'session.opened'
  data: { runtime_version: string; protocol_version: string; capabilities_override?: string[] }
}

export interface SessionResumedEvent extends Envelope {
  type: 'session.resumed'
  data: {
    runtime_version: string
    protocol_version: string
    capabilities_override?: string[]
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

// pattern.*

export interface PatternClassifiedEvent extends Envelope {
  type: 'pattern.classified'
  data: { pattern: string; complexity?: number; confidence?: number; reason?: string }
}

export interface PlanPreviewEvent extends Envelope {
  type: 'plan.preview'
  data: { pattern: string; complexity?: number; reasoning?: string; steps?: string[] }
}

// thinking.*

export interface ThinkingStepEvent extends Envelope {
  type: 'thinking.step'
  data: { step: string; label?: string; detail?: string; elapsed_ms?: number }
}

// token.*

export interface TokenDeltaEvent extends Envelope {
  type: 'token.delta'
  /** `text` is the incremental token text. `role` defaults to "assistant". */
  data: { text: string; role?: 'assistant' | 'tool'; message_id?: string }
}

// message.*

export interface MessageUserAttachmentSummary {
  name: string
  mime_type: string
  byte_length?: number
  path?: string
}

export interface MessageUserEvent extends Envelope {
  type: 'message.user'
  data: { content: string; message_id?: string; attachments?: MessageUserAttachmentSummary[] }
}

export interface MessageAssistantEvent extends Envelope {
  type: 'message.assistant'
  data: { content: string; message_id?: string; run_id?: string; pattern?: string }
}

export interface MessageToolEvent extends Envelope {
  type: 'message.tool'
  data: {
    tool_name: string
    phase?: 'start' | 'progress' | 'end'
    detail?: string
    call_id?: string
  }
}

// tool.*

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
    diff?: { before: string; after: string; language?: string }
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

// hitl.*

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

// worker.*

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

// graph.*

export interface GraphNodeEnterEvent extends Envelope {
  type: 'graph.node.enter'
  data: { node: string; pattern?: string; input_preview?: string }
}

export interface GraphNodeExitEvent extends Envelope {
  type: 'graph.node.exit'
  data: { node: string; pattern?: string; duration_ms?: number; output_preview?: string; error?: string }
}

// memory.*

export interface MemoryLtRecallEvent extends Envelope {
  type: 'memory.lt.recall'
  data: { namespace?: string; query_preview?: string; hits: number; injected_chars: number }
}

export interface MemorySessionWriteEvent extends Envelope {
  type: 'memory.session.write'
  data: { thread: string; run_id?: string; query_preview?: string; output_preview?: string; turn_count?: number }
}

export interface MemorySessionClearedEvent extends Envelope {
  type: 'memory.session.cleared'
  data: { thread: string }
}

export interface MemorySessionTurnPoppedEvent extends Envelope {
  type: 'memory.session.turn_popped'
  data: { thread: string; remaining_turns: number }
}

export interface MemoryLtStoreEvent extends Envelope {
  type: 'memory.lt.store'
  data: { namespace?: string; key?: string; content_preview?: string }
}

// checkpoint.*

export interface CheckpointSavedEvent extends Envelope {
  type: 'checkpoint.saved'
  data: { thread: string; run_id?: string; label?: string }
}

export interface CheckpointRestoredEvent extends Envelope {
  type: 'checkpoint.restored'
  data: { thread: string; resumed_from_run_id?: string }
}

// feedback.*

export interface FeedbackScoredEvent extends Envelope {
  type: 'feedback.scored'
  /** `rating` is a string token: "positive" / "negative" / "neutral" or numeric string */
  data: { run_id: string; rating: string; comment?: string; correct?: string; metadata?: Record<string, unknown> }
}

// metric.*

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
  data: { cost: number; currency?: string; model?: string; phase?: string; worker_id?: string; estimated?: boolean }
}

export interface MetricBudgetApproachingEvent extends Envelope {
  type: 'metric.budget.approaching'
  data: { dimension: 'tokens' | 'cost_usd'; used: number; limit: number; ratio: number }
}

export interface MetricBudgetExhaustedEvent extends Envelope {
  type: 'metric.budget.exhausted'
  data: { dimension: 'tokens' | 'cost_usd'; used: number; limit: number }
}

// error.*

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

// skill.* / prompt.*

export interface SkillLoadedEvent extends Envelope {
  type: 'skill.loaded'
  data: {
    skill_name: string
    source?: 'tool' | 'disk' | 'registry' | 'seed' | 'on_demand' | 'post_run' | string
    version?: string
    body_chars?: number
  }
}

export interface SkillAppliedEvent extends Envelope {
  type: 'skill.applied'
  data: { phase?: 'classifier' | 'worker' | string; injected_chars?: number }
}

export interface SkillLearnedEvent extends Envelope {
  type: 'skill.learned'
  data: {
    skill_name: string
    pattern?: string
    scope?: string
    source?: 'seed' | 'on_demand' | 'post_run' | string
  }
}

export interface PromptRequestedEvent extends Envelope {
  type: 'prompt.requested'
  data: { kind?: 'user_turn' | string; preview?: string }
}

export interface PromptCancelledEvent extends Envelope {
  type: 'prompt.cancelled'
  data: { reason: 'user_aborted' | 'shutdown' | string; detail?: string }
}

// runtime.* & session heartbeat / agent markers / stream liveness

export interface RuntimeReadyEvent extends Envelope {
  type: 'runtime.ready'
  data: {
    agent_name?: string
    cli_tools_enabled?: boolean
    cli_tools_count?: number
    harness_enabled?: boolean
  }
}

export interface RuntimeConfigEvent extends Envelope {
  type: 'runtime.config'
  data: {
    model_id?: string
    tool_names?: string[]
    capabilities?: string[]
    cli_tools_enabled?: boolean
    cli_tools_count?: number
  }
}

export interface RuntimePongEvent extends Envelope {
  type: 'runtime.pong'
  data: { ping_id?: string }
}

export interface RuntimeSchemaEvent extends Envelope {
  type: 'runtime.schema'
  data: { json_schema: Record<string, unknown> }
}

export interface RuntimeToolEntry {
  name: string
  description?: string
}

export interface RuntimeToolsEvent extends Envelope {
  type: 'runtime.tools'
  data: { tools: RuntimeToolEntry[] }
}

export interface RuntimeProviderEntry {
  slug: string
  label: string
  default_model: string
  primary_env_key?: string | null
}

export interface RuntimeProvidersEvent extends Envelope {
  type: 'runtime.providers'
  data: { providers: RuntimeProviderEntry[] }
}

export interface RuntimeSessionsEvent extends Envelope {
  type: 'runtime.sessions'
  data: { sessions: string[] }
}

export interface RuntimeSessionCreatedEvent extends Envelope {
  type: 'runtime.session.created'
  data: { session_id: string }
}

export interface RuntimeSessionRenamedEvent extends Envelope {
  type: 'runtime.session.renamed'
  data: { from_session_id: string; to_session_id: string }
}

export interface RuntimeFileStagedEvent extends Envelope {
  type: 'runtime.file.staged'
  data: { path: string; bytes: number; thread?: string }
}

export interface RuntimeToolResultEvent extends Envelope {
  type: 'runtime.tool.result'
  data: { ok: boolean; result?: unknown; error?: string }
}

export interface RuntimeConfigAppliedEvent extends Envelope {
  type: 'runtime.config.applied'
  data: {
    model_id?: string
    cli_tools_enabled?: boolean
    cli_tools_count?: number
  }
}

export interface RuntimeMCPServersEvent extends Envelope {
  type: 'runtime.mcp.servers'
  data: {
    server_names: string[]
    servers?: Array<{
      name: string
      ok: boolean
      error?: string | null
      tool_count?: number
      tool_names?: string[]
      tool_names_truncated?: boolean
    }>
  }
}

export interface TodosUpdatedEvent extends Envelope {
  type: 'todos.updated'
  data: { items?: Array<Record<string, unknown>> }
}

export interface SessionHeartbeatEvent extends Envelope {
  type: 'session.heartbeat'
  data: { uptime_ms?: number }
}

export interface AgentBusyEvent extends Envelope {
  type: 'agent.busy'
  data: { thread?: string }
}

export interface AgentIdleEvent extends Envelope {
  type: 'agent.idle'
  data: { thread?: string }
}

export interface StreamHeartbeatEvent extends Envelope {
  type: 'stream.heartbeat'
  data: { thread?: string; chars_since_last?: number }
}

// Discriminated union

export type AGPKnownEvent =
  | SessionOpenedEvent
  | SessionResumedEvent
  | SessionClosedEvent
  | SessionHeartbeatEvent
  | PatternClassifiedEvent
  | PlanPreviewEvent
  | ThinkingStepEvent
  | TokenDeltaEvent
  | MessageUserEvent
  | MessageAssistantEvent
  | MessageToolEvent
  | AgentBusyEvent
  | AgentIdleEvent
  | StreamHeartbeatEvent
  | RuntimeReadyEvent
  | RuntimeConfigEvent
  | RuntimePongEvent
  | RuntimeSchemaEvent
  | RuntimeToolsEvent
  | RuntimeProvidersEvent
  | RuntimeSessionsEvent
  | RuntimeSessionCreatedEvent
  | RuntimeSessionRenamedEvent
  | RuntimeFileStagedEvent
  | RuntimeToolResultEvent
  | RuntimeConfigAppliedEvent
  | RuntimeMCPServersEvent
  | TodosUpdatedEvent
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
  | SkillLoadedEvent
  | SkillAppliedEvent
  | SkillLearnedEvent
  | PromptRequestedEvent
  | PromptCancelledEvent
  | MemoryLtRecallEvent
  | MemorySessionWriteEvent
  | MemorySessionClearedEvent
  | MemorySessionTurnPoppedEvent
  | MemoryLtStoreEvent
  | CheckpointSavedEvent
  | CheckpointRestoredEvent
  | FeedbackScoredEvent
  | MetricTokensEvent
  | MetricCostEvent
  | MetricBudgetApproachingEvent
  | MetricBudgetExhaustedEvent
  | ErrorTransientEvent
  | ErrorFatalEvent

/** Known AGP v1 catalogue + additive types above. Wire may carry other `type` strings — the runtime ``dispatch`` default branch must tolerate them (forward-compat). */
export type AGPEvent = AGPKnownEvent

/** Parse and validate one NDJSON / WebSocket frame after ``JSON.parse`` (Zod; see ``agpWireParse.ts``). Prefer importing from this module — do not re-parse in callers. */
export const parseInboundAGPEventJSON = (parsed: unknown): AGPEvent =>
  parseInboundAGPEventJSONWire(parsed) as unknown as AGPEvent

// Inbound commands (CLI / web → Python runtime)

export interface InvokeAttachment {
  name?: string
  mime_type?: string
  data_base64: string
}

export interface CommandInvoke {
  type: 'command.invoke'
  data: { prompt: string; thread?: string; user_id?: string; context?: Record<string, unknown>; attachments?: InvokeAttachment[] }
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

export interface CommandWorkerAssign {
  type: 'command.worker.assign'
  data: {
    worker_id: string
    task: string
    thread?: string
    parent_thread?: string
    pattern?: string
    tools?: string[]
    context?: Record<string, unknown>
  }
}

export interface CommandSessionResume {
  type: 'command.session.resume'
  data: { thread: string; from_seq?: number }
}

export interface CommandPing {
  type: 'command.ping'
  data?: { ping_id?: string }
}

export interface CommandSchemaRequestCmd {
  type: 'command.schema.request'
  data?: Record<string, unknown>
}

export interface CommandToolListCmd {
  type: 'command.tool.list'
  data?: Record<string, unknown>
}

export interface CommandProvidersListCmd {
  type: 'command.providers.list'
  data?: Record<string, unknown>
}

export interface CommandSubscribeCmd {
  type: 'command.subscribe'
  data: { prefixes: string[] }
}

export interface CommandUnsubscribeCmd {
  type: 'command.unsubscribe'
  data?: Record<string, unknown>
}

export interface CommandSessionListCmd {
  type: 'command.session.list'
  data?: Record<string, unknown>
}

export interface CommandSessionCreateCmd {
  type: 'command.session.create'
  data?: { session_id?: string }
}

export interface CommandSessionDeleteCmd {
  type: 'command.session.delete'
  data: { session_id: string }
}

export interface CommandSessionRenameCmd {
  type: 'command.session.rename'
  data: { from_session_id: string; to_session_id: string }
}

export interface CommandToolInvokeCmd {
  type: 'command.tool.invoke'
  data: { name: string; arguments?: Record<string, unknown> }
}

export interface CommandConfigSetCmd {
  type: 'command.config.set'
  data: {
    model_id?: string
    cli_tools?: Record<string, unknown>
    temperature?: number
    top_p?: number
    system_prompt?: string
    budget_token_limit?: number | null
    budget_cost_usd_limit?: number | null
  }
}

export interface CommandMemoryClearCmd {
  type: 'command.memory.clear'
  data?: { thread?: string }
}

export interface CommandMemoryPopLastTurnCmd {
  type: 'command.memory.pop_last_turn'
  data?: { thread?: string }
}

export interface CommandAttachFileCmd {
  type: 'command.attach.file'
  data: { filename: string; content_base64: string; thread?: string }
}

export interface CommandHarnessGitCmd {
  type: 'command.harness.git'
  data?: {
    op?: 'checkpoint' | 'diff' | 'status' | 'checkpoints' | 'revert_hint'
    name?: string
    description?: string
    path?: string
    cached?: boolean
  }
}

export interface CommandPlanPreviewCmd {
  type: 'command.plan.preview'
  data: { prompt: string }
}

export type AGPCommand =
  | CommandInvoke
  | CommandCancel
  | CommandHITLRespond
  | CommandRuntimeShutdown
  | CommandFeedback
  | CommandSnapshotRequest
  | CommandWorkerAssign
  | CommandSessionResume
  | CommandPing
  | CommandSchemaRequestCmd
  | CommandToolListCmd
  | CommandProvidersListCmd
  | CommandSubscribeCmd
  | CommandUnsubscribeCmd
  | CommandSessionListCmd
  | CommandSessionCreateCmd
  | CommandSessionDeleteCmd
  | CommandSessionRenameCmd
  | CommandToolInvokeCmd
  | CommandConfigSetCmd
  | CommandMemoryClearCmd
  | CommandMemoryPopLastTurnCmd
  | CommandAttachFileCmd
  | CommandHarnessGitCmd
  | CommandPlanPreviewCmd

// Utility types

export type ConnectionStatus = 'connecting' | 'open' | 'closed' | 'error'
