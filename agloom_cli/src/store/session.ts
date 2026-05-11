/** CLI session store; `dispatch` is the reducer for inbound AGP events. */

import { create } from 'zustand'
import type { AGPEvent } from '../types/agp.js'

export interface ThinkingStep {
  id: string
  step: string
  label?: string
  detail?: string
  elapsedMs?: number
}

export interface ToolCall {
  id: string
  toolCallId: string
  tool: string
  args: Record<string, unknown>
  status: 'pending' | 'done' | 'error'
  result?: string
  error?: string
  durationMs?: number
}

export interface Worker {
  id: string
  workerId: string
  name?: string
  pattern?: string
  task?: string
  status: 'running' | 'done' | 'failed'
  outputPreview?: string
  error?: string
}

export interface HITLRequest {
  requestId: string
  kind: string
  detail?: string
  tool?: string
  question?: string
  options: string[]
  default?: string
  timeoutMs?: number
}

export interface CompletedTurn {
  id: string
  userMessage: string
  assistantMessage: string
  thinkingSteps: ThinkingStep[]
  toolCalls: ToolCall[]
  workers: Worker[]
  pattern?: string
  tokens?: number
  runId?: string
}

export interface ActiveTurnState {
  id: string
  userMessage: string
  thinkingSteps: ThinkingStep[]
  toolCalls: ToolCall[]
  workers: Worker[]
  streamedTokens: string
  pattern: string | null
  graphNodes: string[]
}

/** One emitted LLM token metric slice (for phase rollup / sidebar). */
export interface MetricTokensSlice {
  id: string
  phase?: string
  workerId?: string
  model?: string
  input: number
  output: number
}

export interface SessionStore {
  // Completed turns — append-only, rendered as <Static>
  completedTurns: CompletedTurn[]

  // The currently in-flight turn (null when idle)
  activeTurn: ActiveTurnState | null

  // Pending HITL gates
  hitlQueue: HITLRequest[]

  // Session / runtime metadata
  sessionId: string | null
  runtimeVersion: string | null
  /** Wall-clock ms when `session.opened` / `session.resumed` arrived (client-side). */
  sessionOpenedAtMs: number | null
  model: string | null
  /** From last `runtime.config` (tool roster on the wire). */
  toolNames: string[] | null
  capabilities: string[] | null
  /** Recent AGP informational lines (config ack, feedback.scored, memory, …). */
  protocolNotes: string[]
  /** Latest todo list from ``todos.updated`` (``write_todos`` meta tool). */
  todos: Array<{ id: string; text: string; done: boolean }>
  totalInputTokens: number
  totalOutputTokens: number
  /** Token deltas attributed to the in-flight turn only (reset each `message.user`). */
  turnInputTokens: number
  turnOutputTokens: number
  /** Recent token metric events (newest last); capped for sidebar / debugging. */
  metricsHistory: MetricTokensSlice[]
  /** Running USD estimate from `metric.cost` deltas. */
  totalCostUsd: number

  // UI status
  status: 'idle' | 'running' | 'thinking' | 'hitl' | 'error' | 'exited'
  errorMessage: string | null

  // Diagnostic lines from stderr (shown in a scrollable log if /diag is open)
  diagnostics: string[]

  /** Per `tool_call_id`: explicit expand/collapse; omitted → default from tool status. */
  toolCallExpandedById: Record<string, boolean>

  /** From `metric.budget.*`. */
  budgetUi: 'ok' | 'approaching' | 'exhausted'

  dispatch: (evt: AGPEvent) => void
  addDiagnostic: (line: string) => void
  clearError: () => void
  markExited: () => void
  reset: () => void
  toggleActiveTurnToolExpandBulk: () => void
  /** Slash/UI helpers — append one line to the metrics sidebar wire notes. */
  appendProtocolNote: (line: string) => void
}

let _seq = 0
const uid = (): string => {
  return `${Date.now().toString(36)}_${(++_seq).toString(36)}`
}

const PROTOCOL_NOTES_CAP = 28

/** Max completed turns kept in memory (Ink ``<Static>`` transcript). Oldest dropped first. */
const COMPLETED_TURNS_CAP = 200

const pushProtocolNotes = (notes: string[], line: string): string[] => {
  return [...notes, line].slice(-PROTOCOL_NOTES_CAP)
}

const newActiveTurn = (userMessage: string): ActiveTurnState => {
  return {
    id: uid(),
    userMessage,
    thinkingSteps: [],
    toolCalls: [],
    workers: [],
    streamedTokens: '',
    pattern: null,
    graphNodes: [],
  }
}

/** Expanded for error/pending tools; collapsed for successful results unless overridden in the map. */
export function effectiveToolCallExpanded(
  tc: ToolCall,
  expandedById: Record<string, boolean>,
): boolean {
  if (Object.prototype.hasOwnProperty.call(expandedById, tc.toolCallId)) {
    return expandedById[tc.toolCallId]!
  }
  return tc.status === 'error' || tc.status === 'pending'
}

export const useSessionStore = create<SessionStore>((set) => ({
  completedTurns: [],
  activeTurn: null,
  hitlQueue: [],
  sessionId: null,
  runtimeVersion: null,
  sessionOpenedAtMs: null,
  model: null,
  toolNames: null,
  capabilities: null,
  protocolNotes: [],
  todos: [],
  totalInputTokens: 0,
  totalOutputTokens: 0,
  turnInputTokens: 0,
  turnOutputTokens: 0,
  metricsHistory: [],
  totalCostUsd: 0,
  status: 'idle',
  errorMessage: null,
  diagnostics: [],
  toolCallExpandedById: {},
  budgetUi: 'ok',

  dispatch: (evt: AGPEvent) =>
    set((s) => {
      switch (evt.type) {
        case 'session.opened':
          return {
            ...s,
            sessionId: evt.session,
            runtimeVersion: evt.data.runtime_version,
            sessionOpenedAtMs: Date.now(),
            status: 'idle',
            toolCallExpandedById: {},
            budgetUi: 'ok',
          }

        case 'session.resumed':
          return {
            ...s,
            sessionId: evt.session,
            runtimeVersion: evt.data.runtime_version,
            sessionOpenedAtMs: Date.now(),
            status: 'idle',
            activeTurn: null,
            toolCallExpandedById: {},
            budgetUi: 'ok',
          }

        case 'session.closed': {
          const isError = evt.data.reason === 'error'
          return {
            ...s,
            status: isError ? 'error' : 'idle',
            errorMessage: isError ? (evt.data.error ?? 'Unknown error') : null,
            activeTurn: null,
          }
        }

        case 'session.heartbeat':
          return s

        case 'stream.heartbeat':
          return s

        case 'agent.busy':
          return {
            ...s,
            status: s.status === 'idle' ? 'running' : s.status,
            protocolNotes: pushProtocolNotes(s.protocolNotes, `Agent busy${evt.data.thread ? ` (${evt.data.thread.slice(0, 12)}…)` : ''}`),
          }

        case 'agent.idle':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(s.protocolNotes, 'Agent idle'),
          }

        case 'runtime.ready': {
          const cli =
            evt.data.cli_tools_count != null
              ? ` · cli_tools=${evt.data.cli_tools_count}`
              : ''
          return {
            ...s,
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
            evt.data.cli_tools_count != null
              ? ` · cli_tools=${evt.data.cli_tools_count}`
              : ''
          return {
            ...s,
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
            evt.data.cli_tools_count != null
              ? ` · cli_tools=${evt.data.cli_tools_count}`
              : ''
          return {
            ...s,
            model: evt.data.model_id ?? s.model,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Config applied · model=${evt.data.model_id ?? 'ok'}${cli}`,
            ),
          }
        }

        case 'todos.updated': {
          const raw = evt.data.items ?? []
          const todos = raw
            .filter((row): row is Record<string, unknown> => row != null && typeof row === 'object')
            .map((row, i) => ({
              id: String(row.id ?? i),
              text: String(row.text ?? row.title ?? ''),
              done: Boolean(row.done ?? row.completed),
            }))
          return {
            ...s,
            todos,
            protocolNotes: pushProtocolNotes(s.protocolNotes, `Todos updated (${todos.length})`),
          }
        }

        case 'runtime.pong':
          return {
            ...s,
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
            protocolNotes: pushProtocolNotes(s.protocolNotes, `Schema · ${keys} top-level keys`),
          }
        }

        case 'runtime.tools': {
          const names = evt.data.tools.map((t) => t.name).join(', ')
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Tools (${evt.data.tools.length}): ${names || '—'}`,
            ),
          }
        }

        case 'runtime.sessions':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Sessions · ${evt.data.sessions.length}: ${evt.data.sessions.slice(0, 6).join(', ') || '—'}${evt.data.sessions.length > 6 ? ' …' : ''}`,
            ),
          }

        case 'runtime.session.created':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(s.protocolNotes, `Session created · ${evt.data.session_id}`),
          }

        case 'runtime.tool.result':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              evt.data.ok ? 'tool.invoke · OK' : `tool.invoke · ${evt.data.error ?? 'error'}`,
            ),
          }

        case 'prompt.requested': {
          const pv = (evt.data.preview ?? '').slice(0, 72)
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Prompt · ${evt.data.kind ?? '?'}${pv ? ` · ${pv}${evt.data.preview && evt.data.preview.length > 72 ? '…' : ''}` : ''}`,
            ),
          }
        }

        case 'prompt.cancelled':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Prompt cancelled · ${evt.data.reason}${evt.data.detail ? ` (${evt.data.detail})` : ''}`,
            ),
          }

        case 'message.user':
          return {
            ...s,
            activeTurn: newActiveTurn(evt.data.content),
            hitlQueue: [],
            status: 'running',
            errorMessage: null,
            turnInputTokens: 0,
            turnOutputTokens: 0,
            toolCallExpandedById: {},
            budgetUi: 'ok',
          }

        case 'pattern.classified':
          if (!s.activeTurn) return s
          return {
            ...s,
            activeTurn: { ...s.activeTurn, pattern: evt.data.pattern },
          }

        case 'thinking.step': {
          if (!s.activeTurn) return s
          const step: ThinkingStep = {
            id: uid(),
            step: evt.data.step,
            label: evt.data.label,
            detail: evt.data.detail,
            elapsedMs: evt.data.elapsed_ms,
          }
          return {
            ...s,
            status: 'thinking',
            activeTurn: {
              ...s.activeTurn,
              thinkingSteps: [...s.activeTurn.thinkingSteps, step],
            },
          }
        }

        case 'token.delta':
          if (!s.activeTurn) return s
          return {
            ...s,
            status: 'running',
            activeTurn: {
              ...s.activeTurn,
              streamedTokens: s.activeTurn.streamedTokens + evt.data.text,
            },
          }

        case 'tool.call.start': {
          if (!s.activeTurn) return s
          const tc: ToolCall = {
            id: uid(),
            toolCallId: evt.data.tool_call_id,
            tool: evt.data.tool,
            args: evt.data.args,
            status: 'pending',
          }
          return {
            ...s,
            activeTurn: {
              ...s.activeTurn,
              toolCalls: [...s.activeTurn.toolCalls, tc],
            },
          }
        }

        case 'tool.call.result': {
          if (!s.activeTurn) return s
          return {
            ...s,
            activeTurn: {
              ...s.activeTurn,
              toolCalls: s.activeTurn.toolCalls.map((tc) =>
                tc.toolCallId === evt.data.tool_call_id
                  ? { ...tc, status: 'done' as const, result: evt.data.output_preview, durationMs: evt.data.duration_ms }
                  : tc
              ),
            },
          }
        }

        case 'tool.call.error': {
          if (!s.activeTurn) return s
          return {
            ...s,
            activeTurn: {
              ...s.activeTurn,
              toolCalls: s.activeTurn.toolCalls.map((tc) =>
                tc.toolCallId === evt.data.tool_call_id
                  ? { ...tc, status: 'error' as const, error: evt.data.error, durationMs: evt.data.duration_ms }
                  : tc
              ),
            },
          }
        }

        case 'worker.spawned': {
          if (!s.activeTurn) return s
          const w: Worker = {
            id: uid(),
            workerId: evt.data.worker_id,
            name: evt.data.name,
            pattern: evt.data.pattern,
            task: evt.data.task,
            status: 'running',
          }
          return {
            ...s,
            activeTurn: { ...s.activeTurn, workers: [...s.activeTurn.workers, w] },
          }
        }

        case 'worker.completed':
          if (!s.activeTurn) return s
          return {
            ...s,
            activeTurn: {
              ...s.activeTurn,
              workers: s.activeTurn.workers.map((w) =>
                w.workerId === evt.data.worker_id
                  ? { ...w, status: 'done', outputPreview: evt.data.output_preview }
                  : w
              ),
            },
          }

        case 'worker.failed':
          if (!s.activeTurn) return s
          return {
            ...s,
            activeTurn: {
              ...s.activeTurn,
              workers: s.activeTurn.workers.map((w) =>
                w.workerId === evt.data.worker_id
                  ? { ...w, status: 'failed', error: evt.data.error }
                  : w
              ),
            },
          }

        case 'graph.node.enter':
          if (!s.activeTurn) return s
          return {
            ...s,
            activeTurn: {
              ...s.activeTurn,
              graphNodes: [...s.activeTurn.graphNodes, evt.data.node],
            },
          }

        case 'graph.node.exit': {
          const ms = evt.data.duration_ms != null ? `${evt.data.duration_ms}ms` : '?'
          const line = `Graph exit · ${evt.data.node} · ${ms}`
          return { ...s, protocolNotes: pushProtocolNotes(s.protocolNotes, line) }
        }

        case 'message.tool':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `message.tool · ${evt.data.tool_name} · ${evt.data.phase ?? '—'}`,
            ),
          }

        case 'hitl.request': {
          const req: HITLRequest = {
            requestId: evt.data.request_id,
            kind: evt.data.kind,
            detail: evt.data.detail,
            tool: evt.data.tool,
            question: evt.data.question,
            options: evt.data.options,
            default: evt.data.default,
            timeoutMs: evt.data.timeout_ms,
          }
          return {
            ...s,
            status: 'hitl',
            hitlQueue: [...s.hitlQueue, req],
          }
        }

        case 'hitl.granted':
        case 'hitl.allowlisted':
        case 'hitl.denied': {
          const remaining = s.hitlQueue.filter((r) => r.requestId !== evt.data.request_id)
          return {
            ...s,
            hitlQueue: remaining,
            status: remaining.length > 0 ? 'hitl' : 'running',
          }
        }

        case 'message.assistant': {
          const active = s.activeTurn
          if (!active) return s

          const turnTok = s.turnInputTokens + s.turnOutputTokens
          const completed: CompletedTurn = {
            id: active.id,
            userMessage: active.userMessage,
            // Prefer the full content sent with the event; fall back to streamed tokens.
            assistantMessage: evt.data.content || active.streamedTokens,
            thinkingSteps: [...active.thinkingSteps],
            toolCalls: [...active.toolCalls],
            workers: [...active.workers],
            pattern: evt.data.pattern ?? active.pattern ?? undefined,
            tokens: turnTok > 0 ? turnTok : undefined,
            runId: evt.data.run_id ?? evt.id,
          }

          return {
            ...s,
            completedTurns: [...s.completedTurns, completed].slice(-COMPLETED_TURNS_CAP),
            activeTurn: null,
            hitlQueue: [],
            status: 'idle',
            turnInputTokens: 0,
            turnOutputTokens: 0,
          }
        }

        case 'metric.tokens': {
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
            totalInputTokens: s.totalInputTokens + inTok,
            totalOutputTokens: s.totalOutputTokens + outTok,
            turnInputTokens: s.activeTurn ? s.turnInputTokens + inTok : s.turnInputTokens,
            turnOutputTokens: s.activeTurn ? s.turnOutputTokens + outTok : s.turnOutputTokens,
            model: s.model ?? evt.data.model,
            metricsHistory: hist,
          }
        }

        case 'metric.cost':
          return {
            ...s,
            totalCostUsd: s.totalCostUsd + evt.data.cost,
            model: s.model ?? evt.data.model,
          }

        case 'metric.budget.approaching':
          return {
            ...s,
            budgetUi: 'approaching',
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Budget · ~80% ${evt.data.dimension} (${Math.round((evt.data.ratio ?? 0) * 100)}%)`,
            ),
          }

        case 'metric.budget.exhausted':
          return {
            ...s,
            budgetUi: 'exhausted',
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Budget · exhausted ${evt.data.dimension}`,
            ),
          }

        case 'feedback.scored': {
          const rid = evt.data.run_id
          const short = rid.length > 14 ? `${rid.slice(0, 12)}…` : rid
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Feedback scored · ${evt.data.rating} · run ${short}`,
            ),
          }
        }

        case 'checkpoint.saved':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Checkpoint saved · ${evt.data.thread}${evt.data.label ? ` · ${evt.data.label}` : ''}`,
            ),
          }

        case 'checkpoint.restored':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Checkpoint restored · ${evt.data.thread}`,
            ),
          }

        case 'memory.session.write':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `memory.session.write · ${evt.data.thread}${evt.data.turn_count != null ? ` · turns ${evt.data.turn_count}` : ''}`,
            ),
          }

        case 'memory.session.cleared':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `memory.session.cleared · ${evt.data.thread}`,
            ),
          }

        case 'memory.lt.recall':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `memory.lt.recall · ${evt.data.hits} hits · +${evt.data.injected_chars} chars`,
            ),
          }

        case 'memory.lt.store':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `memory.lt.store · ${evt.data.key ?? evt.data.namespace ?? '—'}`,
            ),
          }

        case 'skill.loaded':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Skill loaded · ${evt.data.skill_name}${evt.data.source ? ` (${evt.data.source})` : ''}`,
            ),
          }

        case 'skill.applied':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Skill applied · ${evt.data.phase ?? '—'} · +${evt.data.injected_chars ?? 0} chars`,
            ),
          }

        case 'skill.learned':
          return {
            ...s,
            protocolNotes: pushProtocolNotes(
              s.protocolNotes,
              `Skill learned · ${evt.data.skill_name}${evt.data.pattern ? ` · ${evt.data.pattern}` : ''}`,
            ),
          }

        case 'error.fatal':
          return { ...s, status: 'error', errorMessage: evt.data.message }

        case 'error.transient':
          return { ...s, errorMessage: evt.data.message }

        default:
          return s
      }
    }),

  addDiagnostic: (line: string) =>
    set((s) => ({
      ...s,
      diagnostics: [...s.diagnostics.slice(-199), line],
    })),

  clearError: () => set((s) => ({ ...s, errorMessage: null, status: 'idle' })),

  markExited: () => set((s) => ({ ...s, status: 'exited' })),

  appendProtocolNote: (line: string) =>
    set((s) => ({
      ...s,
      protocolNotes: pushProtocolNotes(s.protocolNotes, line),
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

  reset: () =>
    set((s) => ({
      ...s,
      completedTurns: [],
      activeTurn: null,
      hitlQueue: [],
      toolNames: null,
      capabilities: null,
      protocolNotes: [],
      todos: [],
      totalInputTokens: 0,
      totalOutputTokens: 0,
      turnInputTokens: 0,
      turnOutputTokens: 0,
      metricsHistory: [],
      totalCostUsd: 0,
      status: 'idle',
      errorMessage: null,
      toolCallExpandedById: {},
      budgetUi: 'ok',
    })),
}))
