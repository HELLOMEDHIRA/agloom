/** Zod validation for inbound AGP NDJSON frames (after ``JSON.parse``).
 * Matches Pydantic rules in ``agloom/protocol/events.py``: required ``data`` fields are enforced; unknown keys on ``data`` are preserved (forward-compatible with ``extra="allow"``).
 */

import { z } from 'zod'

const envelope = z.object({
  v: z.literal('1'),
  session: z.string(),
  seq: z.number(),
  ts: z.string(),
  id: z.string(),
  thread: z.string().optional(),
  parent: z.string().optional(),
  trace: z.string().optional(),
  type: z.string(),
  data: z.unknown(),
})

const asDataObject = (data: unknown, eventType?: string): Record<string, unknown> => {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    const kind = data === null ? 'null' : Array.isArray(data) ? 'array' : typeof data
    const head = eventType
      ? `AGP event type "${eventType}"`
      : 'AGP event'
    throw new SyntaxError(
      `${head}: \`data\` must be a plain object (got ${kind}). Unknown types still require object-shaped \`data\` for forward compatibility.`,
    )
  }
  return { ...(data as Record<string, unknown>) }
}

/** Parse ``data`` with *schema*; merge validated keys onto the raw wire object (keep extras). */
const mergeData = <T extends z.ZodTypeAny>(raw: Record<string, unknown>, schema: T): z.infer<T> & Record<string, unknown>  => {
  const r = schema.safeParse(raw)
  if (!r.success) {
    const msg = r.error.issues.map((i) => `${i.path.join('.') || 'data'}: ${i.message}`).join('; ')
    throw new SyntaxError(msg)
  }
  return { ...raw, ...(r.data as Record<string, unknown>) } as z.infer<T> & Record<string, unknown>
}

const d = {
  sessionOpened: z.object({
    runtime_version: z.string(),
    protocol_version: z.string(),
    capabilities_override: z.array(z.string()).optional(),
  }),
  sessionResumed: z.object({
    runtime_version: z.string(),
    protocol_version: z.string(),
    capabilities_override: z.array(z.string()).optional(),
    resumed_from_thread: z.string().optional(),
    replayed_from_seq: z.number().optional(),
  }),
  sessionClosed: z.object({
    reason: z.string(),
    duration_ms: z.number().optional(),
    error: z.string().optional(),
  }),
  sessionHeartbeat: z.object({ uptime_ms: z.number().optional() }),
  patternClassified: z.object({
    pattern: z.string(),
    complexity: z.number().optional(),
    confidence: z.number().optional(),
    reason: z.string().optional(),
  }),
  planPreview: z.object({
    pattern: z.string(),
    complexity: z.number().optional(),
    reasoning: z.string().optional(),
    steps: z.array(z.string()).optional(),
  }),
  thinkingStep: z.object({
    step: z.string(),
    label: z.string().optional(),
    detail: z.string().optional(),
    elapsed_ms: z.number().optional(),
  }),
  tokenDelta: z.object({
    text: z.string(),
    role: z.enum(['assistant', 'tool']).optional(),
    message_id: z.string().optional(),
  }),
  messageUser: z.object({
    content: z.string(),
    message_id: z.string().optional(),
    attachments: z
      .array(
        z.object({
          name: z.string(),
          mime_type: z.string(),
          byte_length: z.number().optional(),
          path: z.string().optional(),
        }),
      )
      .optional(),
  }),
  messageAssistant: z.object({
    content: z.string(),
    message_id: z.string().optional(),
    run_id: z.string().optional(),
    pattern: z.string().optional(),
  }),
  messageTool: z.object({
    tool_name: z.string(),
    phase: z.enum(['start', 'progress', 'end']).optional(),
    detail: z.string().optional(),
    call_id: z.string().optional(),
  }),
  agentBusy: z.object({ thread: z.string().optional() }),
  agentIdle: z.object({ thread: z.string().optional() }),
  streamHeartbeat: z.object({
    thread: z.string().optional(),
    chars_since_last: z.number().optional(),
  }),
  runtimeReady: z.object({
    agent_name: z.string().optional(),
    cli_tools_enabled: z.boolean().optional(),
    cli_tools_count: z.number().optional(),
    harness_enabled: z.boolean().optional(),
  }),
  runtimeConfig: z.object({
    model_id: z.string().optional(),
    tool_names: z.array(z.string()).optional(),
    capabilities: z.array(z.string()).optional(),
    cli_tools_enabled: z.boolean().optional(),
    cli_tools_count: z.number().optional(),
  }),
  runtimePong: z.object({ ping_id: z.string().optional() }),
  runtimeSchema: z.object({ json_schema: z.record(z.string(), z.unknown()) }),
  runtimeTools: z.object({
    tools: z.array(
      z.object({
        name: z.string(),
        description: z.string().optional(),
      }),
    ),
  }),
  runtimeProviders: z.object({
    providers: z.array(
      z.object({
        slug: z.string(),
        label: z.string(),
        default_model: z.string(),
        primary_env_key: z.string().nullable().optional(),
      }),
    ),
  }),
  runtimeSessions: z.object({ sessions: z.array(z.string()) }),
  runtimeSessionCreated: z.object({ session_id: z.string() }),
  runtimeSessionRenamed: z.object({
    from_session_id: z.string(),
    to_session_id: z.string(),
  }),
  runtimeFileStaged: z.object({
    path: z.string(),
    bytes: z.number(),
    thread: z.string().optional(),
  }),
  runtimeToolResult: z.object({
    ok: z.boolean(),
    result: z.unknown().optional(),
    error: z.string().optional(),
  }),
  runtimeConfigApplied: z.object({
    model_id: z.string().optional(),
    cli_tools_enabled: z.boolean().optional(),
    cli_tools_count: z.number().optional(),
  }),
  runtimeMCPServers: z.object({
    server_names: z.array(z.string()),
    servers: z
      .array(
        z.object({
          name: z.string(),
          ok: z.boolean(),
          error: z.string().optional().nullable(),
          tool_count: z.number().optional(),
          tool_names: z.array(z.string()).optional(),
          tool_names_truncated: z.boolean().optional(),
        }),
      )
      .optional(),
  }),
  todosUpdated: z.object({
    items: z.array(z.record(z.string(), z.unknown())).optional(),
  }),
  toolCallStart: z.object({
    tool: z.string(),
    tool_call_id: z.string(),
    args: z.record(z.string(), z.unknown()).optional().default({}),
    worker: z.string().optional(),
  }),
  toolCallResult: z.object({
    tool: z.string(),
    tool_call_id: z.string(),
    output_preview: z.string().optional(),
    output_bytes: z.number().optional(),
    duration_ms: z.number().optional(),
    truncated: z.boolean().optional(),
    diff: z
      .object({
        before: z.string(),
        after: z.string(),
        language: z.string().optional(),
      })
      .optional(),
  }),
  toolCallError: z.object({
    tool: z.string(),
    tool_call_id: z.string(),
    error: z.string(),
    error_class: z.string().optional(),
    duration_ms: z.number().optional(),
  }),
  hitlRequest: z.object({
    request_id: z.string(),
    kind: z.string(),
    detail: z.string().optional(),
    options: z.array(z.string()),
    default: z.string().optional(),
    timeout_ms: z.number().optional(),
    agent_name: z.string().optional(),
    tool: z.string().optional(),
    tool_call_id: z.string().optional(),
    args: z.record(z.string(), z.unknown()).optional(),
    worker: z.string().optional(),
    pattern: z.string().optional(),
    question: z.string().optional(),
  }),
  hitlDecision: z.object({
    request_id: z.string(),
    decision: z.string(),
    actor: z.enum(['user', 'auto', 'timeout']).optional(),
    text: z.string().optional(),
    detail: z.string().optional(),
  }),
  workerSpawned: z.object({
    worker_id: z.string(),
    name: z.string().optional(),
    pattern: z.string().optional(),
    task: z.string().optional(),
    parent_worker_id: z.string().optional(),
  }),
  workerCompleted: z.object({
    worker_id: z.string(),
    output_preview: z.string().optional(),
    output_bytes: z.number().optional(),
    duration_ms: z.number().optional(),
    truncated: z.boolean().optional(),
  }),
  workerFailed: z.object({
    worker_id: z.string(),
    error: z.string(),
    error_class: z.string().optional(),
    duration_ms: z.number().optional(),
  }),
  graphNodeEnter: z.object({
    node: z.string(),
    pattern: z.string().optional(),
    input_preview: z.string().optional(),
  }),
  graphNodeExit: z.object({
    node: z.string(),
    pattern: z.string().optional(),
    duration_ms: z.number().optional(),
    output_preview: z.string().optional(),
    error: z.string().optional(),
  }),
  memoryLtRecall: z.object({
    namespace: z.string().optional(),
    query_preview: z.string().optional(),
    hits: z.number(),
    injected_chars: z.number(),
  }),
  memorySessionWrite: z.object({
    thread: z.string(),
    run_id: z.string().optional(),
    query_preview: z.string().optional(),
    output_preview: z.string().optional(),
    turn_count: z.number().optional(),
  }),
  memorySessionCleared: z.object({ thread: z.string() }),
  memorySessionTurnPopped: z.object({ thread: z.string(), remaining_turns: z.number() }),
  memoryLtStore: z.object({
    namespace: z.string().optional(),
    key: z.string().optional(),
    content_preview: z.string().optional(),
  }),
  checkpointSaved: z.object({
    thread: z.string(),
    run_id: z.string().optional(),
    label: z.string().optional(),
  }),
  checkpointRestored: z.object({
    thread: z.string(),
    resumed_from_run_id: z.string().optional(),
  }),
  feedbackScored: z.object({
    run_id: z.string(),
    rating: z.string(),
    comment: z.string().optional(),
    correct: z.string().optional(),
    metadata: z.record(z.string(), z.unknown()).optional(),
  }),
  metricTokens: z.object({
    model: z.string().optional(),
    input_tokens: z.number(),
    output_tokens: z.number(),
    total_tokens: z.number().optional(),
    phase: z.string().optional(),
    worker_id: z.string().optional(),
  }),
  metricCost: z.object({
    cost: z.number(),
    currency: z.string().optional(),
    model: z.string().optional(),
    phase: z.string().optional(),
    worker_id: z.string().optional(),
  }),
  metricBudgetApproaching: z.object({
    dimension: z.string(),
    used: z.number(),
    limit: z.number(),
    ratio: z.number(),
  }),
  metricBudgetExhausted: z.object({
    dimension: z.string(),
    used: z.number(),
    limit: z.number(),
  }),
  errorEvent: z.object({
    severity: z.enum(['transient', 'fatal']),
    message: z.string(),
    error_class: z.string().optional(),
    stage: z.string().optional(),
    retryable: z.boolean().optional(),
  }),
  skillLoaded: z.object({
    skill_name: z.string(),
    source: z.string().optional(),
    version: z.string().optional(),
    body_chars: z.number().optional(),
  }),
  skillApplied: z.object({
    phase: z.string().optional(),
    injected_chars: z.number().optional(),
  }),
  skillLearned: z.object({
    skill_name: z.string(),
    pattern: z.string().optional(),
    scope: z.string().optional(),
    source: z.string().optional(),
  }),
  promptRequested: z.object({
    kind: z.string().optional(),
    preview: z.string().optional(),
  }),
  promptCancelled: z.object({
    reason: z.string(),
    detail: z.string().optional(),
  }),
}

const DATA_BY_TYPE: Record<string, z.ZodTypeAny> = {
  'session.opened': d.sessionOpened,
  'session.resumed': d.sessionResumed,
  'session.closed': d.sessionClosed,
  'session.heartbeat': d.sessionHeartbeat,
  'pattern.classified': d.patternClassified,
  'plan.preview': d.planPreview,
  'thinking.step': d.thinkingStep,
  'token.delta': d.tokenDelta,
  'message.user': d.messageUser,
  'message.assistant': d.messageAssistant,
  'message.tool': d.messageTool,
  'agent.busy': d.agentBusy,
  'agent.idle': d.agentIdle,
  'stream.heartbeat': d.streamHeartbeat,
  'runtime.ready': d.runtimeReady,
  'runtime.config': d.runtimeConfig,
  'runtime.pong': d.runtimePong,
  'runtime.schema': d.runtimeSchema,
  'runtime.tools': d.runtimeTools,
  'runtime.providers': d.runtimeProviders,
  'runtime.sessions': d.runtimeSessions,
  'runtime.session.created': d.runtimeSessionCreated,
  'runtime.session.renamed': d.runtimeSessionRenamed,
  'runtime.file.staged': d.runtimeFileStaged,
  'runtime.tool.result': d.runtimeToolResult,
  'runtime.config.applied': d.runtimeConfigApplied,
  'runtime.mcp.servers': d.runtimeMCPServers,
  'todos.updated': d.todosUpdated,
  'tool.call.start': d.toolCallStart,
  'tool.call.result': d.toolCallResult,
  'tool.call.error': d.toolCallError,
  'hitl.request': d.hitlRequest,
  'hitl.granted': d.hitlDecision,
  'hitl.denied': d.hitlDecision,
  'hitl.allowlisted': d.hitlDecision,
  'worker.spawned': d.workerSpawned,
  'worker.completed': d.workerCompleted,
  'worker.failed': d.workerFailed,
  'graph.node.enter': d.graphNodeEnter,
  'graph.node.exit': d.graphNodeExit,
  'memory.lt.recall': d.memoryLtRecall,
  'memory.session.write': d.memorySessionWrite,
  'memory.session.cleared': d.memorySessionCleared,
  'memory.session.turn_popped': d.memorySessionTurnPopped,
  'memory.lt.store': d.memoryLtStore,
  'checkpoint.saved': d.checkpointSaved,
  'checkpoint.restored': d.checkpointRestored,
  'feedback.scored': d.feedbackScored,
  'metric.tokens': d.metricTokens,
  'metric.cost': d.metricCost,
  'metric.budget.approaching': d.metricBudgetApproaching,
  'metric.budget.exhausted': d.metricBudgetExhausted,
  'error.transient': d.errorEvent,
  'error.fatal': d.errorEvent,
  'skill.loaded': d.skillLoaded,
  'skill.applied': d.skillApplied,
  'skill.learned': d.skillLearned,
  'prompt.requested': d.promptRequested,
  'prompt.cancelled': d.promptCancelled,
}

/**
 * Validate wire JSON as an AGP v1 event. Unknown ``type`` values still require a valid envelope
 * and object-shaped ``data`` (may be empty).
 */
export const parseInboundAGPEventJSONWire = (parsed: unknown): Record<string, unknown> => {
  const o = envelope.safeParse(parsed)
  if (!o.success) {
    const msg = o.error.issues.map((i) => `${i.path.join('.') || 'root'}: ${i.message}`).join('; ')
    throw new SyntaxError(`Invalid AGP envelope: ${msg}`)
  }
  const { data, ...rest } = o.data
  const rawData = asDataObject(data, rest.type)
  const schema = DATA_BY_TYPE[rest.type]
  if (schema) {
    const merged = mergeData(rawData, schema)
    return { ...rest, data: merged }
  }
  // Forward-compatible: no Zod schema for this ``type`` yet — ``data`` is still validated as an object above.
  return { ...rest, data: rawData }
}
