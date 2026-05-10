/**
 * AGP Zustand session store — web platform edition.
 *
 * Same reducer logic as the agloom CLI store (`agloom_cli/src/store/session.ts`).
 * The web store adds richer domain models for the orchestration workspace:
 * - graphNodes: tracked for React Flow visualization
 * - executionTrace: append-only log of every AGP event (for the Trace panel)
 * - artifacts: generated code/docs extracted from assistant messages
 */

import { create } from 'zustand'
import type { AGPEvent } from '../lib/agp/types.js'

// ── Domain types ──────────────────────────────────────────────────────────────

export interface ThinkingStep {
  id: string; step: string; label?: string; detail?: string; elapsedMs?: number
}

export interface ToolCall {
  id: string; toolCallId: string; tool: string
  args: Record<string, unknown>
  status: 'pending' | 'done' | 'error'
  result?: string; error?: string; durationMs?: number
}

export interface Worker {
  id: string; workerId: string; name?: string; pattern?: string; task?: string
  status: 'running' | 'done' | 'failed'
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
  pattern?: string; tokens?: number; runId?: string
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
  summary: string           // human-readable one-liner
  raw: AGPEvent
}

// ── Store interface ───────────────────────────────────────────────────────────

export interface SessionStore {
  completedTurns: CompletedTurn[]
  activeTurn: ActiveTurnState | null
  hitlQueue: HITLRequest[]

  // Runtime metadata
  sessionId: string | null
  runtimeVersion: string | null
  model: string | null
  totalInputTokens: number
  totalOutputTokens: number
  connectionStatus: 'connecting' | 'open' | 'closed' | 'error'

  // Execution trace (all AGP events, ordered by seq)
  executionTrace: TraceEvent[]

  // Active artifacts for the artifact panel
  artifacts: Artifact[]

  status: 'idle' | 'running' | 'thinking' | 'hitl' | 'error' | 'exited'
  errorMessage: string | null

  // Actions
  dispatch: (evt: AGPEvent) => void
  setConnectionStatus: (s: SessionStore['connectionStatus']) => void
  addArtifact: (a: Artifact) => void
  reset: () => void
  clearError: () => void
}

// ── Helpers ───────────────────────────────────────────────────────────────────

let _seq = 0
const uid = () => `${Date.now().toString(36)}_${(++_seq).toString(36)}`

function newActiveTurn(userMessage: string): ActiveTurnState {
  return { id: uid(), userMessage, thinkingSteps: [], toolCalls: [], workers: [], graphNodes: [], streamedTokens: '', pattern: null }
}

function summarise(evt: AGPEvent): string {
  switch (evt.type) {
    case 'session.opened':    return `session opened (v${evt.data.runtime_version})`
    case 'session.closed':    return `session closed (${evt.data.reason})`
    case 'pattern.classified':return `pattern: ${evt.data.pattern} (complexity ${evt.data.complexity ?? '?'})`
    case 'thinking.step':     return `thinking: ${evt.data.label ?? evt.data.step}`
    case 'token.delta':       return `token: "${evt.data.text.slice(0, 20)}"`
    case 'tool.call.start':   return `tool call: ${evt.data.tool}()`
    case 'tool.call.result':  return `tool result: ${evt.data.tool} ✓`
    case 'tool.call.error':   return `tool error: ${evt.data.tool} ✗`
    case 'worker.spawned':    return `worker spawned: ${evt.data.name} [${evt.data.pattern ?? '?'}]`
    case 'worker.completed':  return `worker done: ${evt.data.worker_id}`
    case 'worker.failed':     return `worker failed: ${evt.data.worker_id}`
    case 'hitl.request':      return `HITL gate: ${evt.data.kind}`
    case 'message.assistant': return `response (${evt.data.pattern ?? '?'})`
    case 'metric.tokens':     return `tokens: ${evt.data.input_tokens}↑ ${evt.data.output_tokens}↓`
    case 'graph.node.enter':  return `graph: enter ${evt.data.node}`
    case 'graph.node.exit':   return `graph: exit ${evt.data.node} (${evt.data.duration_ms ?? 0}ms)`
    case 'checkpoint.saved':  return `checkpoint saved (thread=${evt.data.thread})`
    case 'skill.loaded':        return `skill loaded: ${evt.data.skill_name}`
    case 'skill.applied':       return `skill applied (${evt.data.phase ?? '?'}) ${evt.data.injected_chars ?? 0} chars`
    case 'skill.learned':       return `skill learned: ${evt.data.skill_name}`
    case 'prompt.requested':    return `prompt requested (${evt.data.preview?.slice(0, 40) ?? ''})`
    case 'prompt.cancelled':    return `prompt cancelled (${evt.data.reason})`
    case 'error.fatal':       return `fatal: ${evt.data.message}`
    case 'error.transient':   return `transient: ${evt.data.message}`
    default:                  return evt.type
  }
}

const ARTIFACT_EXTRACT_MAX_CHARS = 64_000

function extractArtifacts(content: string, runId?: string): Artifact[] {
  // Skip extraction for very short content (no fences possible) or very large
  // content (defer to avoid blocking the main thread on huge responses).
  if (content.length < 20 || content.indexOf('```') === -1) return []
  // Truncate to cap before running the regex so long outputs don't block rendering.
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

// ── Store ─────────────────────────────────────────────────────────────────────

export const useSessionStore = create<SessionStore>((set) => ({
  completedTurns: [],
  activeTurn: null,
  hitlQueue: [],
  sessionId: null,
  runtimeVersion: null,
  model: null,
  totalInputTokens: 0,
  totalOutputTokens: 0,
  connectionStatus: 'connecting',
  executionTrace: [],
  artifacts: [],
  status: 'idle',
  errorMessage: null,

  dispatch: (evt) => set((s) => {
    // Always append to execution trace (token deltas excluded for performance)
    const trace = evt.type === 'token.delta' ? s.executionTrace : [
      ...s.executionTrace,
      { seq: evt.seq, type: evt.type, ts: evt.ts, summary: summarise(evt), raw: evt } satisfies TraceEvent,
    ]

    switch (evt.type) {
      case 'session.opened':
        return { ...s, executionTrace: trace, sessionId: evt.session, runtimeVersion: evt.data.runtime_version, status: 'idle' }

      case 'session.closed':
        return { ...s, executionTrace: trace, status: evt.data.reason === 'error' ? 'error' : 'idle', activeTurn: null }

      case 'message.user':
        return { ...s, executionTrace: trace, activeTurn: newActiveTurn(evt.data.content), status: 'running', errorMessage: null }

      case 'pattern.classified':
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, pattern: evt.data.pattern } }

      case 'thinking.step': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const step: ThinkingStep = { id: uid(), step: evt.data.step, label: evt.data.label, detail: evt.data.detail, elapsedMs: evt.data.elapsed_ms }
        return { ...s, executionTrace: trace, status: 'thinking', activeTurn: { ...s.activeTurn, thinkingSteps: [...s.activeTurn.thinkingSteps, step] } }
      }

      case 'token.delta':
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return { ...s, executionTrace: trace, status: 'running', activeTurn: { ...s.activeTurn, streamedTokens: s.activeTurn.streamedTokens + evt.data.text } }

      case 'tool.call.start': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const tc: ToolCall = { id: uid(), toolCallId: evt.data.tool_call_id, tool: evt.data.tool, args: evt.data.args, status: 'pending' }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, toolCalls: [...s.activeTurn.toolCalls, tc] } }
      }

      case 'tool.call.result':
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, toolCalls: s.activeTurn.toolCalls.map((tc) => tc.toolCallId === evt.data.tool_call_id ? { ...tc, status: 'done' as const, result: evt.data.output_preview, durationMs: evt.data.duration_ms } : tc) } }

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

      case 'graph.node.enter': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        const gn: GraphNode = { nodeId: evt.data.node, pattern: evt.data.pattern, enterAt: evt.ts }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, graphNodes: [...s.activeTurn.graphNodes, gn] } }
      }

      case 'graph.node.exit': {
        if (!s.activeTurn) return { ...s, executionTrace: trace }
        return { ...s, executionTrace: trace, activeTurn: { ...s.activeTurn, graphNodes: s.activeTurn.graphNodes.map((n) => n.nodeId === evt.data.node ? { ...n, exitAt: evt.ts, durationMs: evt.data.duration_ms } : n) } }
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
        const content = evt.data.content || active.streamedTokens
        const newArtifacts = extractArtifacts(content, evt.data.run_id ?? evt.id)
        const turn: CompletedTurn = {
          id: active.id, userMessage: active.userMessage, assistantMessage: content,
          thinkingSteps: [...active.thinkingSteps], toolCalls: [...active.toolCalls],
          workers: [...active.workers], graphNodes: [...active.graphNodes],
          pattern: evt.data.pattern ?? active.pattern ?? undefined,
          tokens: undefined, runId: evt.data.run_id ?? evt.id, artifacts: newArtifacts, timestamp: new Date(),
        }
        return { ...s, executionTrace: trace, completedTurns: [...s.completedTurns, turn], activeTurn: null, hitlQueue: [], status: 'idle', artifacts: [...s.artifacts, ...newArtifacts] }
      }

      case 'metric.tokens':
        return { ...s, executionTrace: trace, totalInputTokens: s.totalInputTokens + evt.data.input_tokens, totalOutputTokens: s.totalOutputTokens + evt.data.output_tokens, model: s.model ?? evt.data.model }

      case 'error.fatal':
        return { ...s, executionTrace: trace, status: 'error', errorMessage: evt.data.message }

      case 'error.transient':
        return { ...s, executionTrace: trace, errorMessage: evt.data.message }

      default:
        return { ...s, executionTrace: trace }
    }
  }),

  setConnectionStatus: (s) => set((prev) => ({ ...prev, connectionStatus: s })),
  addArtifact: (a) => set((prev) => ({ ...prev, artifacts: [...prev.artifacts, a] })),
  clearError: () => set((s) => ({ ...s, errorMessage: null, status: 'idle' })),
  reset: () => set((s) => ({ ...s, completedTurns: [], activeTurn: null, hitlQueue: [], executionTrace: [], artifacts: [], totalInputTokens: 0, totalOutputTokens: 0, status: 'idle', errorMessage: null })),
}))
