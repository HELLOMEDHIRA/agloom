/** Web session store: AGP `dispatch` reducer + trace/artifacts/graph panels. */

import { create } from 'zustand'
import type { AGPEvent, AGPKnownEvent } from '../lib/agp/types.js'
import { isAgpKnownEvent } from '../lib/agp/agpEventGuards.js'
import {
  finalizeAssistantMessage,
  formatTurnTokenRollup,
  stripAgloomToolResultEnvelope,
} from '../lib/utils/assistantText.js'
import { isStrayToolJsonText, stripStrayToolJsonFromStream } from '../lib/utils/strayToolJson.js'

export interface ThinkingStep {
  id: string; step: string; label?: string; detail?: string; elapsedMs?: number
}

export interface ToolCall {
  id: string; toolCallId: string; tool: string
  args: Record<string, unknown>
  status: 'pending' | 'done' | 'error'
  result?: string; error?: string; durationMs?: number
  /** From `tool.call.result` when edit tools return structured diff. */
  resultDiff?: { before: string; after: string; language?: string }
}

export interface Worker {
  id: string; workerId: string; name?: string; pattern?: string; task?: string
  status: 'running' | 'done' | 'failed' | 'halted'
  outputPreview?: string; error?: string
}

export interface GraphNode {
  nodeId: string; pattern?: string
  enterAt: string; exitAt?: string; durationMs?: number
}

export interface HITLRequest {
  requestId: string; kind: string; detail?: string; tool?: string
  question?: string; options: string[]; default?: string; timeoutMs?: number
}

export interface Artifact {
  id: string; type: 'code' | 'markdown' | 'json' | 'text'
  language?: string; content: string; title?: string; runId?: string
}

export interface CompletedTurn {
  id: string; userMessage: string; assistantMessage: string
  thinkingSteps: ThinkingStep[]; toolCalls: ToolCall[]
  workers: Worker[]; graphNodes: GraphNode[]
  pattern?: string; tokens?: string; runId?: string
  artifacts: Artifact[]
  timestamp: Date
}

export interface ActiveTurnState {
  id: string; userMessage: string
  thinkingSteps: ThinkingStep[]; toolCalls: ToolCall[]
  workers: Worker[]; graphNodes: GraphNode[]
  streamedTokens: string; pattern: string | null
}

export interface TraceEvent {
  seq: number; type: string; ts: string
  summary: string
  raw: AGPEvent
}

/** One emitted LLM token metric slice (sidebar / observability parity with CLI). */
export interface MetricTokensSlice {
  id: string
  phase?: string
  workerId?: string
  model?: string
  input: number
  output: number
}

export interface SessionStore {
  completedTurns: CompletedTurn[]
  activeTurn: ActiveTurnState | null
  hitlQueue: HITLRequest[]
  /** Relative paths from `runtime.file.staged` (prepended to next user invoke). */
  pendingAttachmentPaths: string[]

  sessionId: string | null
  runtimeVersion: string | null
  /** Client clock when `session.opened` / `session.resumed` arrived. */
  sessionOpenedAtMs: number | null
  model: string | null
  /** From last `runtime.config`. */
  toolNames: string[] | null
  capabilities: string[] | null
  /** Recent AGP informational lines (runtime acks, memory, resume, …). */
  protocolNotes: string[]
  totalInputTokens: number
  totalOutputTokens: number
  /** Last ``metric.tokens`` seq applied — ignore duplicate/out-of-order replays. */
  lastMetricTokensSeq: number
  /** Token deltas attributed to the in-flight turn only (reset each `message.user`). */
  turnInputTokens: number
  turnOutputTokens: number
  metricsHistory: MetricTokensSlice[]
  /** Running estimate from `metric.cost` deltas. */
  totalCostUsd: number

  /** Per `tool_call_id` expand/collapse overrides. */
  toolCallExpandedById: Record<string, boolean>
  /** From `metric.budget.*`. */
  budgetUi: 'ok' | 'approaching' | 'exhausted'
  /** Last `metric.budget.*` payload (modal copy). */
  budgetLast: { dimension: string; used: number; limit: number } | null

  connectionStatus: 'connecting' | 'open' | 'closed' | 'error'
  executionTrace: TraceEvent[]
  artifacts: Artifact[]

  status: 'idle' | 'running' | 'thinking' | 'hitl' | 'error' | 'exited'
  errorMessage: string | null

  dispatch: (evt: AGPEvent) => void
  setConnectionStatus: (s: SessionStore['connectionStatus']) => void
  addArtifact: (a: Artifact) => void
  reset: () => void
  clearError: () => void
  /** Cleared by ChatPane after paths are prepended to an invocation. */
  clearPendingAttachments: () => void
  toggleActiveTurnToolExpandBulk: () => void
  toggleToolCallExpand: (toolCallId: string) => void
  setBudgetUiOk: () => void

  /** Curated LLM providers from `runtime.providers`. */
  providerCatalog: Array<{
    slug: string
    label: string
    default_model: string
    primary_env_key?: string | null
  }> | null
  /** Last `runtime.sessions` ids (for workspace nav / search). */
  sessionCatalogIds: string[]
}

let _seq = 0
const uid = () => `${Date.now().toString(36)}_${(++_seq).toString(36)}`

const pushProtocolNotes = (notes: string[], line: string): string[] => {
  return [...notes, line]
}

const stringifyWireResultPreview = (v: unknown): string => {
  if (v == null) return ''
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v)
  } catch {
    return String(v)
  }
}

const newActiveTurn = (userMessage: string): ActiveTurnState => {
  return { id: uid(), userMessage, thinkingSteps: [], toolCalls: [], workers: [], graphNodes: [], streamedTokens: '', pattern: null }
}

const toolNameSet = (names: string[] | null | undefined): Set<string> =>
  new Set((names ?? []).map((n) => n.trim()).filter(Boolean))

const sanitizeAssistantText = (text: string, allowed: Set<string>): string => {
  if (!text.trim()) return text
  return stripStrayToolJsonFromStream(text, allowed, { permissive: allowed.size === 0 }).trim()
}

/** Tool bodies are always visible in the transcript (no expand/collapse). */
export const effectiveToolCallExpanded = (
  _tc: ToolCall,
  _expandedById: Record<string, boolean>,
): boolean => true

const summarise = (evt: AGPKnownEvent): string => {
  switch (evt.type) {
    case 'session.opened':
      return `session opened (v${evt.data.runtime_version})`
    case 'session.resumed': {
      const seq = evt.data.replayed_from_seq
      const th = evt.data.resumed_from_thread
      return `session resumed${seq != null ? ` · replay from seq=${seq}` : ''}${th ? ` · thread ${th}` : ''}`
    }
    case 'session.closed':
      return `session closed (${evt.data.reason})`
    case 'session.heartbeat':
      return `session heartbeat (${evt.data.uptime_ms ?? '?'}ms uptime)`
    case 'stream.heartbeat':
      return `stream heartbeat${evt.data.thread ? ` · ${evt.data.thread}` : ''}`
    case 'agent.busy':
      return `agent busy${evt.data.thread ? ` · ${evt.data.thread}` : ''}`
    case 'agent.idle':
      return 'agent idle'
    case 'runtime.ready':
      return `runtime ready (${evt.data.agent_name ?? 'agent'})`
    case 'runtime.config':
      return `runtime.config · model=${evt.data.model_id ?? '—'} · ${(evt.data.tool_names ?? []).length} tools`
    case 'runtime.config.applied':
      return `config applied · model=${evt.data.model_id ?? 'ok'}`
    case 'runtime.mcp.servers': {
      const names = evt.data.server_names ?? []
      return `MCP servers · ${names.join(', ') || 'none'}`
    }
    case 'runtime.pong':
      return `pong${evt.data.ping_id ? ` · ${evt.data.ping_id}` : ''}`
    case 'runtime.schema': {
      const keys = evt.data.json_schema && typeof evt.data.json_schema === 'object'
        ? Object.keys(evt.data.json_schema).length
        : 0
      return `schema · ${keys} top-level keys`
    }
    case 'runtime.tools':
      return `tools (${evt.data.tools.length}): ${evt.data.tools.map((t) => t.name).join(', ') || '—'}`
    case 'runtime.providers':
      return `providers · ${evt.data.providers.length}`
    case 'runtime.sessions':
      return `sessions · ${evt.data.sessions.length}`
    case 'runtime.session.created':
      return `session created · ${evt.data.session_id}`
    case 'runtime.session.renamed':
      return `session renamed · ${evt.data.from_session_id} → ${evt.data.to_session_id}`
    case 'runtime.file.staged':
      return `file staged · ${evt.data.path} (${evt.data.bytes} B)`
    case 'runtime.tool.result':
      return evt.data.ok
        ? `tool.invoke · OK${evt.data.result !== undefined ? ` · ${stringifyWireResultPreview(evt.data.result)}` : ''}`
        : `tool.invoke · ${evt.data.error ?? 'error'}`
    case 'pattern.classified':
      return `pattern: ${evt.data.pattern} (complexity ${evt.data.complexity ?? '?'})`
    case 'plan.preview': {
      const steps = evt.data.steps ?? []
      const joined = steps.join(' · ')
      return `plan.preview · ${evt.data.pattern} · ${joined}`
    }
    case 'thinking.step':
      return `thinking: ${evt.data.label ?? evt.data.step}`
    case 'token.delta':
      return `token: "${evt.data.text}"`
    case 'message.user':
      return 'message.user'
    case 'message.tool':
      return `message.tool · ${evt.data.tool_name} · ${evt.data.phase ?? '—'}`
    case 'tool.call.start':
      return `tool call: ${evt.data.tool}()`
    case 'tool.call.result':
      return `tool result: ${evt.data.tool} ✓`
    case 'tool.call.error':
      return `tool error: ${evt.data.tool} ✗`
    case 'worker.spawned':
      return `worker spawned: ${evt.data.name} [${evt.data.pattern ?? '?'}]`
    case 'worker.completed':
      return `worker done: ${evt.data.worker_id}`
    case 'worker.failed':
      return `worker failed: ${evt.data.worker_id}`
    case 'worker.halted':
      return `worker halted: ${evt.data.worker_id} (${evt.data.reason ?? 'HALT_ALL'})`
    case 'hitl.request':
      return `HITL gate: ${evt.data.kind}`
    case 'hitl.granted':
    case 'hitl.allowlisted':
    case 'hitl.denied':
      return `hitl · ${evt.type} · ${evt.data.request_id}`
    case 'graph.node.enter':
      return `graph: enter ${evt.data.node}`
    case 'graph.node.exit':
      return `graph: exit ${evt.data.node} (${evt.data.duration_ms ?? 0}ms)`
    case 'orchestration.step': {
      const d = evt.data
      return `orchestration · d${d.depth ?? 0} ${d.pattern} · ${d.action}`
    }
    case 'memory.session.write':
      return `memory.session.write · ${evt.data.thread}${evt.data.turn_count != null ? ` · turns ${evt.data.turn_count}` : ''}`
    case 'memory.session.cleared':
      return `memory.session.cleared · ${evt.data.thread}`
    case 'memory.session.turn_popped':
      return `memory.session.turn_popped · ${evt.data.thread} · ${evt.data.remaining_turns} left`
    case 'memory.lt.recall':
      return `memory.lt.recall · ${evt.data.hits} hits · +${evt.data.injected_chars} chars`
    case 'memory.lt.store':
      return `memory.lt.store · ${evt.data.key ?? evt.data.namespace ?? '—'}`
    case 'checkpoint.saved':
      return `checkpoint saved (thread=${evt.data.thread})`
    case 'checkpoint.restored':
      return `checkpoint restored · ${evt.data.thread}`
    case 'feedback.scored':
      return `feedback · ${evt.data.rating} · ${evt.data.run_id}`
    case 'metric.tokens':
      return `tokens: ${evt.data.input_tokens}↑ ${evt.data.output_tokens}↓`
    case 'metric.cost':
      return `cost +${evt.data.cost} ${evt.data.currency ?? 'USD'}`
    case 'metric.budget.approaching':
      return `budget ~80% ${evt.data.dimension}`
    case 'metric.budget.exhausted':
      return `budget exhausted ${evt.data.dimension}`
    case 'message.assistant':
      return `response (${evt.data.pattern ?? '?'})`
    case 'skill.loaded':
      return `skill loaded: ${evt.data.skill_name}`
    case 'skill.applied':
      return `skill applied (${evt.data.phase ?? '?'}) ${evt.data.injected_chars ?? 0} chars`
    case 'skill.learned':
      return `skill learned: ${evt.data.skill_name}`
    case 'prompt.requested':
      return `prompt requested (${evt.data.preview ?? ''})`
    case 'prompt.cancelled':
      return `prompt cancelled (${evt.data.reason})`
    case 'todos.updated':
      return `todos updated (${evt.data.items?.length ?? 0})`
    case 'error.fatal':
      return `fatal: ${evt.data.message}`
    case 'error.transient':
      return `transient: ${evt.data.message}`
    default: {
      const _exhaustive: never = evt
      return _exhaustive
    }
  }
}

const ARTIFACT_EXTRACT_MAX_CHARS = 64_000

const extractArtifacts = (content: string, runId?: string): Artifact[] => {
  if (content.length < 20 || content.indexOf('```') === -1) return []
  const safe = content.length > ARTIFACT_EXTRACT_MAX_CHARS
    ? content.slice(0, ARTIFACT_EXTRACT_MAX_CHARS)
    : content
  const artifacts: Artifact[] = []
  const fence = /```(\w*)\n([\s\S]*?)```/g
  let m: RegExpExecArray | null
  while ((m = fence.exec(safe)) !== null) {
    const lang = m[1] ?? ''
    const body = m[2] ?? ''
    if (body.trim().length < 20) continue
    artifacts.push({
      id: uid(),
      type: lang === '' || lang === 'text' ? 'text'
        : lang === 'json' ? 'json'
          : lang === 'markdown' || lang === 'md' ? 'markdown'
            : 'code',
      language: lang || undefined,
      content: body,
      runId,
    })
  }
  return artifacts
}

export const useSessionStore = create<SessionStore>((set) => ({
  completedTurns: [],
  activeTurn: null,
  hitlQueue: [],
  pendingAttachmentPaths: [],
  sessionId: null,
  runtimeVersion: null,
  sessionOpenedAtMs: null,
  model: null,
  toolNames: null,
  capabilities: null,
  protocolNotes: [],
  totalInputTokens: 0,
  totalOutputTokens: 0,
  lastMetricTokensSeq: 0,
  turnInputTokens: 0,
  turnOutputTokens: 0,
  metricsHistory: [],
  totalCostUsd: 0,
  toolCallExpandedById: {},
  budgetUi: 'ok',
  budgetLast: null,
  connectionStatus: 'connecting',
  executionTrace: [],
  artifacts: [],
  status: 'idle',
  errorMessage: null,
  providerCatalog: null,
  sessionCatalogIds: [],

  dispatch: (evt) => set((s) => {
    if (!isAgpKnownEvent(evt)) {
      const trace: TraceEvent[] = [
        ...s.executionTrace,
        {
          seq: evt.seq,
          type: evt.type,
          ts: evt.ts,
          summary: `unknown: ${evt.type}`,
          raw: evt,
        },
      ]
      return {
        ...s,
        executionTrace: trace,
        protocolNotes: pushProtocolNotes(
          s.protocolNotes,
          `Unknown / unhandled AGP event · ${evt.type}`,
        ),
      }
    }

    const trace = evt.type === 'token.delta' ? s.executionTrace : [
      ...s.executionTrace,
      { seq: evt.seq, type: evt.type, ts: evt.ts, summary: summarise(evt), raw: evt } satisfies TraceEvent,
    ]

    switch (evt.type) {
      case 'session.opened':
        return {
          ...s,
          executionTrace: trace,
          sessionId: evt.session,
          runtimeVersion: evt.data.runtime_version,
          sessionOpenedAtMs: Date.now(),
          status: 'idle',
          toolCallExpandedById: {},
          budgetUi: 'ok',
          budgetLast: null,
          lastMetricTokensSeq: 0,
        }

      case 'session.resumed':
        return {
          ...s,
          executionTrace: trace,
          sessionId: evt.session,
          runtimeVersion: evt.data.runtime_version,
          sessionOpenedAtMs: Date.now(),
          status: 'idle',
          activeTurn: null,
          toolCallExpandedById: {},
          budgetUi: 'ok',
          budgetLast: null,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Session resumed${evt.data.replayed_from_seq != null ? ` · replay from seq=${evt.data.replayed_from_seq}` : ''}${evt.data.resumed_from_thread ? ` · ${evt.data.resumed_from_thread}` : ''}`,
          ),
        }

      case 'session.closed': {
        const isError = evt.data.reason === 'error'
        return {
          ...s,
          executionTrace: trace,
          status: isError ? 'error' : 'idle',
          errorMessage: isError ? (evt.data.error ?? 'Unknown error') : null,
          activeTurn: null,
        }
      }

      case 'session.heartbeat':
      case 'stream.heartbeat':
        return { ...s, executionTrace: trace }

      case 'agent.busy':
        return {
          ...s,
          executionTrace: trace,
          status: s.status === 'idle' ? 'running' : s.status,
          protocolNotes: pushProtocolNotes(s.protocolNotes, `Agent busy${evt.data.thread ? ` (${evt.data.thread})` : ''}`),
        }

      case 'agent.idle':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(s.protocolNotes, 'Agent idle'),
        }

      case 'runtime.ready': {
        const cli =
          evt.data.cli_tools_count != null ? ` · cli_tools=${evt.data.cli_tools_count}` : ''
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Runtime ready (${evt.data.agent_name ?? 'agent'})${cli}`,
          ),
        }
      }

      case 'runtime.config': {
        const tools = evt.data.tool_names ?? []
        const caps = evt.data.capabilities ?? []
        const cli =
          evt.data.cli_tools_count != null ? ` · cli_tools=${evt.data.cli_tools_count}` : ''
        return {
          ...s,
          executionTrace: trace,
          model: evt.data.model_id ?? s.model,
          toolNames: tools.length ? tools : s.toolNames,
          capabilities: caps.length ? caps : s.capabilities,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `runtime.config · model=${evt.data.model_id ?? '—'} · ${tools.length} tools${cli}`,
          ),
        }
      }

      case 'runtime.config.applied': {
        const cli =
          evt.data.cli_tools_count != null ? ` · cli_tools=${evt.data.cli_tools_count}` : ''
        return {
          ...s,
          executionTrace: trace,
          model: evt.data.model_id ?? s.model,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Config applied · model=${evt.data.model_id ?? 'ok'}${cli}`,
          ),
        }
      }

      case 'runtime.mcp.servers': {
        const names = evt.data.server_names ?? []
        const raw = evt.data.servers ?? []
        const parts = raw.map((r) => {
          if (r.ok) {
            const n = r.tool_count ?? r.tool_names?.length ?? 0
            return `${r.name}:ok(${n} tools)`
          }
          return `${r.name}:FAIL${r.error ? `(${String(r.error)})` : ''}`
        })
        const detail = parts.length ? ` · ${parts.join(' · ')}` : ''
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `MCP servers: ${names.join(', ') || 'none'}${detail}`,
          ),
        }
      }

      case 'todos.updated': {
        const n = evt.data.items?.length ?? 0
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(s.protocolNotes, `Todos updated (${n})`),
        }
      }

      case 'runtime.pong':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Pong${evt.data.ping_id ? ` · ${evt.data.ping_id}` : ''}`,
          ),
        }

      case 'runtime.schema': {
        const keys = evt.data.json_schema && typeof evt.data.json_schema === 'object'
          ? Object.keys(evt.data.json_schema).length
          : 0
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(s.protocolNotes, `Schema · ${keys} top-level keys`),
        }
      }

      case 'runtime.tools': {
        const names = evt.data.tools.map((t) => t.name).join(', ')
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Tools (${evt.data.tools.length}): ${names || '—'}`,
          ),
        }
      }

      case 'runtime.sessions':
        return {
          ...s,
          executionTrace: trace,
          sessionCatalogIds: [...evt.data.sessions],
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Sessions · ${evt.data.sessions.length}: ${evt.data.sessions.join(', ') || '—'}`,
          ),
        }

      case 'runtime.providers':
        return {
          ...s,
          executionTrace: trace,
          providerCatalog: evt.data.providers.map((p) => ({
            slug: p.slug,
            label: p.label,
            default_model: p.default_model,
            primary_env_key: p.primary_env_key,
          })),
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Providers · ${evt.data.providers.length}`,
          ),
        }

      case 'runtime.session.created':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(s.protocolNotes, `Session created · ${evt.data.session_id}`),
        }

      case 'runtime.session.renamed':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Session renamed · ${evt.data.from_session_id} → ${evt.data.to_session_id}`,
          ),
        }

      case 'runtime.file.staged':
        return {
          ...s,
          executionTrace: trace,
          pendingAttachmentPaths: [...s.pendingAttachmentPaths, evt.data.path],
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `File staged · ${evt.data.path} (${evt.data.bytes} B)`,
          ),
        }

      case 'runtime.tool.result':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            (() => {
              const base = evt.data.ok ? 'tool.invoke · OK' : `tool.invoke · ${evt.data.error ?? 'error'}`
              if (!evt.data.ok || evt.data.result === undefined) return base
              const preview = stringifyWireResultPreview(evt.data.result)
              return preview.length > 0 ? `${base} · ${preview}` : base
            })(),
          ),
        }

      case 'message.user':
        return {
          ...s,
          executionTrace: trace,
          activeTurn: newActiveTurn(evt.data.content),
          hitlQueue: [],
          status: 'running',
          errorMessage: null,
          turnInputTokens: 0,
          turnOutputTokens: 0,
          toolCallExpandedById: {},
          budgetUi: 'ok',
          budgetLast: null,
        }

      case 'pattern.classified':
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, pattern: evt.data.pattern } }

      case 'plan.preview': {
        const steps = evt.data.steps ?? []
        const joined = steps.join('\n')
        const line = `plan.preview · ${evt.data.pattern} · c=${evt.data.complexity ?? 0}${joined ? `\n${joined}` : ''}`
        const next = { ...s, executionTrace: trace, protocolNotes: pushProtocolNotes(s.protocolNotes, line) }
        if (!s.activeTurn) return next
        const planDetail = evt.data.reasoning?.trim() || undefined
        return {
          ...next,
          activeTurn: {
            ...s.activeTurn,
            thinkingSteps: [
              ...s.activeTurn.thinkingSteps,
              {
                id: uid(),
                step: 'plan',
                label: `Routing · ${evt.data.pattern}`,
                detail: planDetail,
                elapsedMs: undefined,
              },
            ],
          },
        }
      }

      case 'thinking.step': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const step: ThinkingStep = { id: uid(), step: evt.data.step, label: evt.data.label, detail: evt.data.detail, elapsedMs: evt.data.elapsed_ms }
        return { ...s, executionTrace: trace, status: 'thinking', activeTurn: { ...s.activeTurn, thinkingSteps: [...s.activeTurn.thinkingSteps, step] } }
      }

      case 'token.delta': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const chunk = evt.data.text ?? ''
        const allowed = toolNameSet(s.toolNames)
        const combined = s.activeTurn.streamedTokens + chunk
        let streamedTokens = combined
        if (combined.trim().length > 0) {
          const permissive = allowed.size === 0
          if (isStrayToolJsonText(combined.trim(), allowed, { permissive })) {
            streamedTokens = s.activeTurn.streamedTokens
          } else {
            streamedTokens = sanitizeAssistantText(combined, allowed)
          }
        }
        return {
          ...s,
          executionTrace: trace,
          status: 'running',
          activeTurn: { ...s.activeTurn, streamedTokens },
        }
      }

      case 'tool.call.start': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const tc: ToolCall = { id: uid(), toolCallId: evt.data.tool_call_id, tool: evt.data.tool, args: evt.data.args, status: 'pending' }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, toolCalls: [...s.activeTurn.toolCalls, tc] } }
      }

      case 'tool.call.result': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const d = evt.data.diff
        const resultDiff =
          d && typeof d === 'object' && typeof (d as { before?: unknown }).before === 'string' && typeof (d as { after?: unknown }).after === 'string'
            ? {
                before: (d as { before: string }).before,
                after: (d as { after: string }).after,
                language: typeof (d as { language?: unknown }).language === 'string' ? (d as { language: string }).language : undefined,
              }
            : undefined
        return {
          ...s,
          executionTrace: trace,
          activeTurn: {
            ...s.activeTurn,
            toolCalls: s.activeTurn.toolCalls.map((tc) =>
              tc.toolCallId === evt.data.tool_call_id
                ? {
                    ...tc,
                    status: 'done' as const,
                    result: evt.data.output_preview,
                    durationMs: evt.data.duration_ms,
                    ...(resultDiff ? { resultDiff } : {}),
                  }
                : tc,
            ),
          },
        }
      }

      case 'tool.call.error':
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, toolCalls: s.activeTurn.toolCalls.map((tc) => tc.toolCallId === evt.data.tool_call_id ? { ...tc, status: 'error' as const, error: evt.data.error, durationMs: evt.data.duration_ms } : tc) } }

      case 'worker.spawned': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const w: Worker = { id: uid(), workerId: evt.data.worker_id, name: evt.data.name, pattern: evt.data.pattern, task: evt.data.task, status: 'running' }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, workers: [...s.activeTurn.workers, w] } }
      }

      case 'worker.completed':
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, workers: s.activeTurn.workers.map((w) => w.workerId === evt.data.worker_id ? { ...w, status: 'done', outputPreview: evt.data.output_preview } : w) } }

      case 'worker.failed':
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, workers: s.activeTurn.workers.map((w) => w.workerId === evt.data.worker_id ? { ...w, status: 'failed', error: evt.data.error } : w) } }

      case 'worker.halted':
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return {
          ...s,
          executionTrace: trace,
          activeTurn: {
            ...s.activeTurn,
            workers: s.activeTurn.workers.map((w) =>
              w.workerId === evt.data.worker_id
                ? {
                    ...w,
                    status: 'halted',
                    error: evt.data.reason,
                    outputPreview: evt.data.output_preview,
                  }
                : w,
            ),
          },
        }

      case 'graph.node.enter': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const gn: GraphNode = { nodeId: evt.data.node, pattern: evt.data.pattern, enterAt: evt.ts }
        const preview = evt.data.input_preview ?? evt.data.pattern ?? evt.data.node
        return {
          ...s,
          executionTrace: trace,
          activeTurn: {
            ...s.activeTurn,
            graphNodes: [...s.activeTurn.graphNodes, gn],
            thinkingSteps: [
              ...s.activeTurn.thinkingSteps,
              {
                id: uid(),
                step: evt.data.node,
                label: `graph → ${evt.data.node}`,
                detail: preview || undefined,
                elapsedMs: undefined,
              },
            ],
          },
        }
      }

      case 'graph.node.exit': {
        const ms = evt.data.duration_ms != null ? `${evt.data.duration_ms}ms` : '?'
        const noteLine = `Graph exit · ${evt.data.node} · ${ms}`
        const detail = evt.data.output_preview ?? evt.data.error ?? undefined
        const nextTurn = !s.activeTurn
          ? s.activeTurn
          : {
              ...s.activeTurn,
              graphNodes: s.activeTurn.graphNodes.map((n) =>
                n.nodeId === evt.data.node ? { ...n, exitAt: evt.ts, durationMs: evt.data.duration_ms } : n,
              ),
              thinkingSteps: [
                ...s.activeTurn.thinkingSteps,
                {
                  id: uid(),
                  step: evt.data.node,
                  label: `graph · ${evt.data.node} · ${ms}`,
                  detail,
                  elapsedMs: evt.data.duration_ms,
                },
              ],
            }
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(s.protocolNotes, noteLine),
          activeTurn: nextTurn,
        }
      }

      case 'orchestration.step': {
        if (!s.activeTurn) {
          return {
            ...s,
            executionTrace: trace,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Orchestration · d${evt.data.depth ?? 0} ${evt.data.pattern} · ${evt.data.action}`,
            ),
          }
        }
        const d = evt.data
        const label = `d${d.depth ?? 0} ${d.pattern} · ${d.action}`
        const step: ThinkingStep = {
          id: uid(),
          step: 'orchestration',
          label,
          detail: d.reason ?? d.output_preview ?? d.input_preview,
          elapsedMs: d.duration_ms,
        }
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(s.protocolNotes, `Orchestration · ${label}`),
          activeTurn: { ...s.activeTurn, thinkingSteps: [...s.activeTurn.thinkingSteps, step] },
        }
      }

      case 'message.tool':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `message.tool · ${evt.data.tool_name} · ${evt.data.phase ?? '—'}`,
          ),
        }

      case 'hitl.request': {
        const req: HITLRequest = { requestId: evt.data.request_id, kind: evt.data.kind, detail: evt.data.detail, tool: evt.data.tool, question: evt.data.question, options: evt.data.options, default: evt.data.default, timeoutMs: evt.data.timeout_ms }
        return { ...s, executionTrace: trace, status: 'hitl', hitlQueue: [...s.hitlQueue, req] }
      }

      case 'hitl.granted':
      case 'hitl.allowlisted':
      case 'hitl.denied': {
        const remaining = s.hitlQueue.filter((r) => r.requestId !== evt.data.request_id)
        return { ...s, executionTrace: trace, hitlQueue: remaining, status: remaining.length > 0 ? 'hitl' : 'running' }
      }

      case 'message.assistant': {
        const active = s.activeTurn
        if (!active) return { ...s, executionTrace: trace }
        const allowed = toolNameSet(s.toolNames)
        const wireBody = sanitizeAssistantText(
          stripAgloomToolResultEnvelope(evt.data.content ?? ''),
          allowed,
        )
        const streamBody = sanitizeAssistantText(
          stripAgloomToolResultEnvelope(active.streamedTokens),
          allowed,
        )
        let assistantBody =
          wireBody.trim().length > 0
            ? wireBody
            : streamBody.trim().length > 0
              ? streamBody
              : finalizeAssistantMessage(evt.data.content ?? '', active.streamedTokens)
        assistantBody = sanitizeAssistantText(assistantBody, allowed)
        if (!assistantBody.trim()) {
          const permissive = allowed.size === 0
          if (
            isStrayToolJsonText((evt.data.content ?? '').trim(), allowed, { permissive }) ||
            isStrayToolJsonText(active.streamedTokens.trim(), allowed, { permissive })
          ) {
            assistantBody =
              '(model emitted invalid tool JSON; runtime recovers via structured tool calls)'
          }
        }
        const newArtifacts = extractArtifacts(assistantBody, evt.data.run_id ?? evt.id)
        const turnTokLabel = formatTurnTokenRollup(s.turnInputTokens, s.turnOutputTokens)
        const turn: CompletedTurn = {
          id: active.id,
          userMessage: active.userMessage,
          assistantMessage: assistantBody,
          thinkingSteps: [...active.thinkingSteps],
          toolCalls: [...active.toolCalls],
          workers: [...active.workers],
          graphNodes: [...active.graphNodes],
          pattern: evt.data.pattern ?? active.pattern ?? undefined,
          tokens: turnTokLabel,
          runId: evt.data.run_id ?? evt.id,
          artifacts: newArtifacts,
          timestamp: new Date(),
        }
        return {
          ...s,
          executionTrace: trace,
          completedTurns: [...s.completedTurns, turn],
          activeTurn: null,
          hitlQueue: [],
          status: 'idle',
          artifacts: [...s.artifacts, ...newArtifacts],
          turnInputTokens: 0,
          turnOutputTokens: 0,
        }
      }

      case 'metric.tokens': {
        if (evt.seq <= s.lastMetricTokensSeq) {
          return { ...s, executionTrace: trace }
        }
        const slice: MetricTokensSlice = {
          id: uid(),
          phase: evt.data.phase,
          workerId: evt.data.worker_id,
          model: evt.data.model,
          input: evt.data.input_tokens,
          output: evt.data.output_tokens,
        }
        const hist = [...s.metricsHistory, slice].slice(-80)
        const inTok = evt.data.input_tokens
        const outTok = evt.data.output_tokens
        return {
          ...s,
          executionTrace: trace,
          totalInputTokens: s.totalInputTokens + inTok,
          totalOutputTokens: s.totalOutputTokens + outTok,
          lastMetricTokensSeq: evt.seq,
          turnInputTokens: s.activeTurn ? s.turnInputTokens + inTok : s.turnInputTokens,
          turnOutputTokens: s.activeTurn ? s.turnOutputTokens + outTok : s.turnOutputTokens,
          model: s.model ?? evt.data.model,
          metricsHistory: hist,
        }
      }

      case 'metric.cost':
        return {
          ...s,
          executionTrace: trace,
          totalCostUsd: s.totalCostUsd + evt.data.cost,
          model: s.model ?? evt.data.model,
        }

      case 'metric.budget.approaching':
        return {
          ...s,
          executionTrace: trace,
          budgetUi: 'approaching',
          budgetLast: {
            dimension: evt.data.dimension,
            used: evt.data.used,
            limit: evt.data.limit,
          },
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Budget · ~80% ${evt.data.dimension} (${Math.round(evt.data.ratio * 100)}%)`,
          ),
        }

      case 'metric.budget.exhausted':
        return {
          ...s,
          executionTrace: trace,
          budgetUi: 'exhausted',
          budgetLast: {
            dimension: evt.data.dimension,
            used: evt.data.used,
            limit: evt.data.limit,
          },
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Budget · exhausted ${evt.data.dimension}`,
          ),
        }

      case 'feedback.scored': {
        const rid = evt.data.run_id
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Feedback scored · ${evt.data.rating} · run ${rid}`,
          ),
        }
      }

      case 'checkpoint.saved':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Checkpoint saved · ${evt.data.thread}${evt.data.label ? ` · ${evt.data.label}` : ''}`,
          ),
        }

      case 'checkpoint.restored':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Checkpoint restored · ${evt.data.thread}`,
          ),
        }

      case 'memory.session.write':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `memory.session.write · ${evt.data.thread}${evt.data.turn_count != null ? ` · turns ${evt.data.turn_count}` : ''}`,
          ),
        }

      case 'memory.session.cleared':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `memory.session.cleared · ${evt.data.thread}`,
          ),
        }

      case 'memory.session.turn_popped': {
        const turns = s.completedTurns
        const nextTurns = turns.length > 0 ? turns.slice(0, -1) : turns
        return {
          ...s,
          executionTrace: trace,
          completedTurns: nextTurns,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Undo · thread ${evt.data.thread} · ${evt.data.remaining_turns} turn(s) in session memory`,
          ),
        }
      }

      case 'memory.lt.recall':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `memory.lt.recall · ${evt.data.hits} hits · +${evt.data.injected_chars} chars`,
          ),
        }

      case 'memory.lt.store':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `memory.lt.store · ${evt.data.key ?? evt.data.namespace ?? '—'}`,
          ),
        }

      case 'skill.loaded':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Skill loaded · ${evt.data.skill_name}${evt.data.source ? ` (${evt.data.source})` : ''}`,
          ),
        }

      case 'skill.applied':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Skill applied · ${evt.data.phase ?? '—'} · +${evt.data.injected_chars ?? 0} chars`,
          ),
        }

      case 'skill.learned':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Skill learned · ${evt.data.skill_name}${evt.data.pattern ? ` · ${evt.data.pattern}` : ''}`,
          ),
        }

      case 'prompt.requested': {
        const pv = evt.data.preview ?? ''
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Prompt · ${evt.data.kind ?? '?'}${pv ? ` · ${pv}` : ''}`,
          ),
        }
      }

      case 'prompt.cancelled':
        return {
          ...s,
          executionTrace: trace,
          protocolNotes: pushProtocolNotes(
            s.protocolNotes,
            `Prompt cancelled · ${evt.data.reason}${evt.data.detail ? ` (${evt.data.detail})` : ''}`,
          ),
        }

      case 'error.fatal':
        return { ...s, executionTrace: trace, status: 'error', errorMessage: evt.data.message }

      case 'error.transient':
        return { ...s, executionTrace: trace, errorMessage: evt.data.message }

      default:
        return { ...s, executionTrace: trace }
    }
  }),

  setConnectionStatus: (st) => set((prev) => ({ ...prev, connectionStatus: st })),
  addArtifact: (a) => set((prev) => ({ ...prev, artifacts: [...prev.artifacts, a] })),
  clearError: () => set((s) => ({ ...s, errorMessage: null, status: 'idle' })),
  clearPendingAttachments: () => set((s) => ({ ...s, pendingAttachmentPaths: [] })),

  reset: () => set((s) => ({
    ...s,
    completedTurns: [],
    activeTurn: null,
    hitlQueue: [],
    pendingAttachmentPaths: [],
    executionTrace: [],
    artifacts: [],
    sessionId: null,
    runtimeVersion: null,
    model: null,
    protocolNotes: [],
    sessionOpenedAtMs: null,
    toolNames: null,
    capabilities: null,
    totalInputTokens: 0,
    totalOutputTokens: 0,
    lastMetricTokensSeq: 0,
    turnInputTokens: 0,
    turnOutputTokens: 0,
    metricsHistory: [],
    totalCostUsd: 0,
    status: 'idle',
    errorMessage: null,
    providerCatalog: null,
    sessionCatalogIds: [],
    toolCallExpandedById: {},
    budgetUi: 'ok',
    budgetLast: null,
  })),

  toggleActiveTurnToolExpandBulk: () =>
    set((s) => {
      const at = s.activeTurn
      if (!at || at.toolCalls.length === 0) return s
      const next: Record<string, boolean> = { ...s.toolCallExpandedById }
      for (const tc of at.toolCalls) {
        const cur = effectiveToolCallExpanded(tc, next)
        next[tc.toolCallId] = !cur
      }
      return { ...s, toolCallExpandedById: next }
    }),

  toggleToolCallExpand: (toolCallId: string) =>
    set((s) => {
      const fromActive = s.activeTurn?.toolCalls.find((t) => t.toolCallId === toolCallId)
      const fromCompleted = fromActive
        ? undefined
        : s.completedTurns.flatMap((t) => t.toolCalls).find((t) => t.toolCallId === toolCallId)
      const tc = fromActive ?? fromCompleted
      if (!tc) return s
      const cur = effectiveToolCallExpanded(tc, s.toolCallExpandedById)
      return {
        ...s,
        toolCallExpandedById: { ...s.toolCallExpandedById, [toolCallId]: !cur },
      }
    }),

  setBudgetUiOk: () => set((s) => ({ ...s, budgetUi: 'ok' })),
}))
