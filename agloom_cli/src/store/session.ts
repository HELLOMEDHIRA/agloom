/** CLI session store; `dispatch` is the reducer for inbound AGP events. */

import { create } from 'zustand'
import type { AGPEvent } from '../types/agp.js'
import { dispatchAgpEvent, pushProtocolNotes } from './dispatchAgpEvent.js'

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

export interface McpServerStatusRow {
  name: string
  ok: boolean
  toolCount: number
  error?: string | null
}

export interface SessionStore {
  // Completed turns — append-only transcript (live tree; avoids Ink <Static> + flex layout gaps on resume)
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
  /** Last prompt sent to the runtime before `message.user` arrives (invoke ack / skipped invoke UX). */
  outboundPrompt: string | null

  // Diagnostic lines from stderr (shown in a scrollable log if /diag is open)
  diagnostics: string[]

  /** Per `tool_call_id`: explicit expand/collapse; omitted → default from tool status. */
  toolCallExpandedById: Record<string, boolean>

  /** From `metric.budget.*`. */
  budgetUi: 'ok' | 'approaching' | 'exhausted'

  // ── Enhanced session info ────────────────────────────────────────────
  sessionStartedAt: string | null
  sessionUpdatedAt: string | null
  /** From ``runtime.ready.session_memory_mode`` (before first ``memory.*`` event). */
  sessionMemoryMode: string | null
  memoryEnabled: boolean | null
  skillsEnabled: boolean | null
  harnessEnabled: boolean | null
  cliToolsEnabled: boolean | null
  cliToolsCount: number | null
  mcpServerNames: string[]
  /** Per-server MCP status from ``runtime.mcp.servers`` (tool counts, ok/err). */
  mcpServerRows: McpServerStatusRow[]
  autoApprovedTools: string[]
  filesUpdated: string[]

  /** When false, completed turns show a one-line thinking summary (Ctrl+Y expands). */
  expandHistoryThinking: boolean
  /** When false, the in-flight turn shows one live-updating thinking line (Ctrl+Y expands). */
  expandActiveThinking: boolean

  dispatch: (evt: AGPEvent) => void
  addDiagnostic: (line: string) => void
  clearError: () => void
  markExited: () => void
  reset: () => void
  toggleActiveTurnToolExpandBulk: () => void
  /** Slash/UI helpers — append one line to the metrics sidebar wire notes. */
  appendProtocolNote: (line: string) => void
  toggleExpandHistoryThinking: () => void
  /** Ctrl+Y / ``/think``: expand current turn thinking if any, else transcript thinking rows. */
  toggleThinkingUiExpand: () => void
}

/** Read-oriented tools: show full result by default when done (still toggle with Ctrl+T / ``/tools``). */
const TOOL_RESULTS_EXPAND_WHEN_DONE = new Set<string>([
  'read_file',
  'grep_files',
  'glob_files',
  'list_dir',
  'notebook_read',
  'fetch_url',
  'read_url_markdown',
  'which',
])

export const effectiveToolCallExpanded = (
  tc: ToolCall,
  expandedById: Record<string, boolean>,
): boolean => {
  if (Object.prototype.hasOwnProperty.call(expandedById, tc.toolCallId)) {
    return expandedById[tc.toolCallId]!
  }
  if (tc.status === 'error' || tc.status === 'pending') return true
  if (tc.status === 'done' && TOOL_RESULTS_EXPAND_WHEN_DONE.has(tc.tool)) return true
  return false
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
  outboundPrompt: null,
  diagnostics: [],
  toolCallExpandedById: {},
  budgetUi: 'ok',
  sessionStartedAt: null,
  sessionUpdatedAt: null,
  sessionMemoryMode: null,
  memoryEnabled: null,
  skillsEnabled: null,
  harnessEnabled: null,
  cliToolsEnabled: null,
  cliToolsCount: null,
  mcpServerNames: [],
  mcpServerRows: [],
  autoApprovedTools: [],
  filesUpdated: [],
  expandHistoryThinking: false,
  expandActiveThinking: true,

  dispatch: (evt: AGPEvent) => set((s) => dispatchAgpEvent(s, evt)),

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

  toggleExpandHistoryThinking: () =>
    set((s) => ({ ...s, expandHistoryThinking: !s.expandHistoryThinking })),

  toggleThinkingUiExpand: () =>
    set((s) => {
      const at = s.activeTurn
      if (at && at.thinkingSteps.length > 0) {
        return { ...s, expandActiveThinking: !s.expandActiveThinking }
      }
      return { ...s, expandHistoryThinking: !s.expandHistoryThinking }
    }),

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
      expandHistoryThinking: false,
      expandActiveThinking: true,
      totalInputTokens: 0,
      totalOutputTokens: 0,
      turnInputTokens: 0,
      turnOutputTokens: 0,
      metricsHistory: [],
      totalCostUsd: 0,
      status: 'idle',
      errorMessage: null,
      outboundPrompt: null,
      toolCallExpandedById: {},
      budgetUi: 'ok',
    })),
}))
