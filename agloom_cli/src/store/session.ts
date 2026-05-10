/**
 * Zustand session store — single source of truth for the agloom CLI terminal UI.
 *
 * Design principles:
 *   - `completedTurns` holds finished conversation turns; rendered via
 *     Ink's <Static> so they are written once and never re-rendered.
 *   - `activeTurn` accumulates everything for the current in-progress turn
 *     (streaming tokens, thinking steps, tool calls, workers). It re-renders
 *     on every token delta but only occupies the bottom portion of the screen.
 *   - The `dispatch` action is the *only* way to mutate state from AGP events;
 *     this keeps the reducer logic co-located and testable.
 */

import { create } from 'zustand'
import type { AGPEvent } from '../types/agp.js'

// ── Domain types ──────────────────────────────────────────────────────────────

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

// ── Store interface ───────────────────────────────────────────────────────────

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

  // ── Actions ──
  dispatch: (evt: AGPEvent) => void
  addDiagnostic: (line: string) => void
  clearError: () => void
  markExited: () => void
  reset: () => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────

let _seq = 0
function uid(): string {
  return `${Date.now().toString(36)}_${(++_seq).toString(36)}`
}

function newActiveTurn(userMessage: string): ActiveTurnState {
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

// ── Store ─────────────────────────────────────────────────────────────────────

export const useSessionStore = create<SessionStore>((set) => ({
  completedTurns: [],
  activeTurn: null,
  hitlQueue: [],
  sessionId: null,
  runtimeVersion: null,
  sessionOpenedAtMs: null,
  model: null,
  totalInputTokens: 0,
  totalOutputTokens: 0,
  turnInputTokens: 0,
  turnOutputTokens: 0,
  metricsHistory: [],
  totalCostUsd: 0,
  status: 'idle',
  errorMessage: null,
  diagnostics: [],

  // ── Event reducer ──────────────────────────────────────────────────────────
  dispatch: (evt: AGPEvent) =>
    set((s) => {
      switch (evt.type) {
        // ── session ──
        case 'session.opened':
          return {
            ...s,
            sessionId: evt.session,
            runtimeVersion: evt.data.runtime_version,
            sessionOpenedAtMs: Date.now(),
            status: 'idle',
          }

        case 'session.resumed':
          // Runtime has resumed a prior session from a checkpoint. Update the session id and
          // reset transient UI state so the new stream renders cleanly from this point forward.
          return {
            ...s,
            sessionId: evt.session,
            runtimeVersion: evt.data.runtime_version,
            sessionOpenedAtMs: Date.now(),
            status: 'idle',
            activeTurn: null,
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

        // ── message.user — marks the start of a new turn ──
        case 'message.user':
          return {
            ...s,
            activeTurn: newActiveTurn(evt.data.content),
            hitlQueue: [],
            status: 'running',
            errorMessage: null,
            turnInputTokens: 0,
            turnOutputTokens: 0,
          }

        // ── pattern ──
        case 'pattern.classified':
          if (!s.activeTurn) return s
          return {
            ...s,
            activeTurn: { ...s.activeTurn, pattern: evt.data.pattern },
          }

        // ── thinking ──
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

        // ── token streaming ──
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

        // ── tool call ──
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

        // ── workers ──
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

        // ── graph nodes ──
        case 'graph.node.enter':
          if (!s.activeTurn) return s
          return {
            ...s,
            activeTurn: {
              ...s.activeTurn,
              graphNodes: [...s.activeTurn.graphNodes, evt.data.node],
            },
          }

        // ── HITL ──
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

        // ── message.assistant — finalises the active turn ──
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
            completedTurns: [...s.completedTurns, completed],
            activeTurn: null,
            hitlQueue: [],
            status: 'idle',
            turnInputTokens: 0,
            turnOutputTokens: 0,
          }
        }

        // ── metrics ──
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

        // ── errors ──
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

  reset: () =>
    set((s) => ({
      ...s,
      completedTurns: [],
      activeTurn: null,
      hitlQueue: [],
      totalInputTokens: 0,
      totalOutputTokens: 0,
      turnInputTokens: 0,
      turnOutputTokens: 0,
      metricsHistory: [],
      totalCostUsd: 0,
      status: 'idle',
      errorMessage: null,
    })),
}))
