/** CLI session store; `dispatch` is the reducer for inbound AGP events. */

import { create } from 'zustand'
import type { AGPEvent, RuntimeProviderEntry } from '../types/agp.js'
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
  status: 'running' | 'done' | 'failed' | 'halted'
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
  /** LangGraph thread from the latest ``session.opened`` / ``session.resumed`` envelope. */
  activeThreadId: string | null
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
  /** Last ``metric.tokens`` seq applied — ignore duplicate/out-of-order replays. */
  lastMetricTokensSeq: number
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
  /** Full rows from last ``runtime.providers`` (sidebar / protocol). */
  providerRows: RuntimeProviderEntry[]
  autoApprovedTools: string[]
  filesUpdated: string[]

  /** Main chat column width (terminal cols minus optional metrics sidebar). */
  mainColumnWidth: number

  /** Shared wall clock (ms) for uptime displays — one interval in ``App``. */
  wallClockMs: number

  /** When true, reasoning steps are hidden (Ctrl+Y / ``/think`` toggles). Default: show dim inline trace. */
  hideThinkingTrace: boolean

  dispatch: (evt: AGPEvent) => void
  addDiagnostic: (line: string) => void
  clearError: () => void
  markExited: () => void
  reset: () => void
  toggleActiveTurnToolExpandBulk: () => void
  /** Slash/UI helpers — append one line to the metrics sidebar wire notes. */
  appendProtocolNote: (line: string) => void
  /** Ctrl+Y / ``/think``: show or hide dim reasoning trace in the transcript. */
  toggleHideThinkingTrace: () => void
  setMainColumnWidth: (width: number) => void
  setWallClockMs: (ms: number) => void
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
  activeThreadId: null,
  runtimeVersion: null,
  sessionOpenedAtMs: null,
  model: null,
  toolNames: null,
  capabilities: null,
  protocolNotes: [],
  todos: [],
  totalInputTokens: 0,
  totalOutputTokens: 0,
  lastMetricTokensSeq: 0,
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
  providerRows: [],
  autoApprovedTools: [],
  filesUpdated: [],
  hideThinkingTrace: false,
  mainColumnWidth: 80,
  wallClockMs: Date.now(),

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

  toggleHideThinkingTrace: () => set((s) => ({ ...s, hideThinkingTrace: !s.hideThinkingTrace })),

  setMainColumnWidth: (width: number) =>
    set((s) => (s.mainColumnWidth === width ? s : { ...s, mainColumnWidth: width })),

  setWallClockMs: (ms: number) =>
    set((s) => (s.wallClockMs === ms ? s : { ...s, wallClockMs: ms })),

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
      hideThinkingTrace: false,
      totalInputTokens: 0,
      totalOutputTokens: 0,
      lastMetricTokensSeq: 0,
      turnInputTokens: 0,
      turnOutputTokens: 0,
      metricsHistory: [],
      totalCostUsd: 0,
      status: s.status === 'exited' ? 'exited' : 'idle',
      errorMessage: null,
      outboundPrompt: null,
      toolCallExpandedById: {},
      budgetUi: 'ok',
      autoApprovedTools: [],
      filesUpdated: [],
      providerRows: [],
      mcpServerRows: [],
      mcpServerNames: [],
      sessionStartedAt: null,
      sessionUpdatedAt: null,
      sessionMemoryMode: null,
      memoryEnabled: null,
      skillsEnabled: null,
      harnessEnabled: null,
      cliToolsEnabled: null,
      cliToolsCount: null,
      diagnostics: [],
    })),
}))
