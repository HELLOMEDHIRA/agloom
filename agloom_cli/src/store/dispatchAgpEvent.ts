/** Apply one inbound AGP event to the session store (reducer extracted from ``session.ts``). */

import type {
  ActiveTurnState,
  CompletedTurn,
  HITLRequest,
  MetricTokensSlice,
  SessionStore,
  ThinkingStep,
  ToolCall,
  Worker,
} from './session.js'
import type { AGPEvent } from '../types/agp.js'

const PROTOCOL_NOTES_CAP = 28
const COMPLETED_TURNS_CAP = 200

let _seq = 0
const uid = (): string => `${Date.now().toString(36)}_${(++_seq).toString(36)}_${Math.random().toString(36).slice(2, 8)}`

export const pushProtocolNotes = (notes: string[], line: string): string[] => {
  if (notes.length < PROTOCOL_NOTES_CAP) return [...notes, line]
  return [...notes.slice(notes.length - (PROTOCOL_NOTES_CAP - 1)), line]
}

function stringifyWireResultPreview(v: unknown, max = 520): string {
  if (v == null) return ''
  if (typeof v === 'string') return v.length > max ? `${v.slice(0, max - 1)}…` : v
  try {
    const j = JSON.stringify(v)
    return j.length > max ? `${j.slice(0, max - 1)}…` : j
  } catch {
    return String(v).slice(0, max)
  }
}

const newActiveTurn = (userMessage: string): ActiveTurnState => ({
  id: uid(),
  userMessage,
  thinkingSteps: [],
  toolCalls: [],
  workers: [],
  streamedTokens: '',
  pattern: null,
  graphNodes: [],
})

/** Apply one inbound AGP event to the current store snapshot. */
export function dispatchAgpEvent(s: SessionStore, evt: AGPEvent): SessionStore {
  switch (evt.type) {
    case 'session.opened': {
      const now = new Date().toISOString()
      return {
        ...s,
        sessionId: evt.session,
        runtimeVersion: evt.data.runtime_version,
        sessionOpenedAtMs: Date.now(),
        sessionStartedAt: now,
        sessionUpdatedAt: now,
        status: 'idle',
        toolCallExpandedById: {},
        budgetUi: 'ok',
        filesUpdated: [],
      }
    }

    case 'session.resumed': {
      const now = new Date().toISOString()
      return {
        ...s,
        sessionId: evt.session,
        runtimeVersion: evt.data.runtime_version,
        sessionOpenedAtMs: Date.now(),
        sessionStartedAt: s.sessionStartedAt ?? now,
        sessionUpdatedAt: now,
        status: 'idle',
        activeTurn: null,
        toolCallExpandedById: {},
        budgetUi: 'ok',
      }
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
      const cli = evt.data.cli_tools_count != null ? ` · cli_tools=${evt.data.cli_tools_count}` : ''
      const harness = evt.data.harness_enabled != null ? ` · harness=${evt.data.harness_enabled ? 'on' : 'off'}` : ''
      return {
        ...s,
        cliToolsEnabled: evt.data.cli_tools_enabled ?? s.cliToolsEnabled,
        cliToolsCount: evt.data.cli_tools_count ?? s.cliToolsCount,
        harnessEnabled: evt.data.harness_enabled ?? s.harnessEnabled,
        protocolNotes: pushProtocolNotes(
          s.protocolNotes,
          `Runtime ready (${evt.data.agent_name ?? 'agent'})${cli}${harness}`,
        ),
      }
    }

    case 'runtime.config': {
      const tools = evt.data.tool_names ?? []
      const caps = evt.data.capabilities ?? []
      const cli = evt.data.cli_tools_count != null ? ` · cli_tools=${evt.data.cli_tools_count}` : ''
      return {
        ...s,
        model: evt.data.model_id ?? s.model,
        toolNames: tools.length ? tools : s.toolNames,
        capabilities: caps.length ? caps : s.capabilities,
        cliToolsEnabled: evt.data.cli_tools_enabled ?? s.cliToolsEnabled,
        cliToolsCount: evt.data.cli_tools_count ?? s.cliToolsCount,
        protocolNotes: pushProtocolNotes(
          s.protocolNotes,
          `runtime.config · model=${evt.data.model_id ?? '—'} · ${tools.length} tools${cli}`,
        ),
      }
    }

    case 'runtime.config.applied': {
      const cli = evt.data.cli_tools_count != null ? ` · cli_tools=${evt.data.cli_tools_count}` : ''
      return {
        ...s,
        model: evt.data.model_id ?? s.model,
        protocolNotes: pushProtocolNotes(
          s.protocolNotes,
          `Config applied · model=${evt.data.model_id ?? 'ok'}${cli}`,
        ),
      }
    }

    case 'runtime.mcp.servers': {
      const names = evt.data.server_names ?? []
      return {
        ...s,
        mcpServerNames: names,
        protocolNotes: pushProtocolNotes(
          s.protocolNotes,
          `MCP servers: ${names.join(', ') || 'none'}`,
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
        protocolNotes: pushProtocolNotes(s.protocolNotes, `Pong${evt.data.ping_id ? ` · ${evt.data.ping_id}` : ''}`),
      }

    case 'runtime.schema': {
      const keys =
        evt.data.json_schema && typeof evt.data.json_schema === 'object' ? Object.keys(evt.data.json_schema).length : 0
      return {
        ...s,
        protocolNotes: pushProtocolNotes(s.protocolNotes, `Schema · ${keys} top-level keys`),
      }
    }

    case 'runtime.tools': {
      const names = evt.data.tools.map((t) => t.name).join(', ')
      return {
        ...s,
        protocolNotes: pushProtocolNotes(s.protocolNotes, `Tools (${evt.data.tools.length}): ${names || '—'}`),
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
          (() => {
            const base = evt.data.ok ? 'tool.invoke · OK' : `tool.invoke · ${evt.data.error ?? 'error'}`
            if (!evt.data.ok || evt.data.result === undefined) return base
            const preview = stringifyWireResultPreview(evt.data.result)
            return preview.length > 0 ? `${base} · ${preview}` : base
          })(),
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

    case 'plan.preview': {
      const steps = evt.data.steps ?? []
      const joined = steps.slice(0, 8).join(' · ')
      const more = steps.length > 8 ? ` …+${steps.length - 8}` : ''
      const line = `plan.preview · ${evt.data.pattern} · c=${evt.data.complexity ?? 0}${joined ? ` · ${joined}${more}` : ''}`
      return { ...s, protocolNotes: pushProtocolNotes(s.protocolNotes, line) }
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
      const isFileWrite = evt.data.tool === 'write_file' || evt.data.tool === 'edit_file'
      let filesUpdated = s.filesUpdated
      if (isFileWrite) {
        const match = s.activeTurn.toolCalls.find((tc) => tc.toolCallId === evt.data.tool_call_id)
        const fname = match ? String(match.args?.path ?? '') : ''
        if (fname && !filesUpdated.includes(fname)) filesUpdated = [...filesUpdated, fname]
      }
      return {
        ...s,
        filesUpdated,
        activeTurn: {
          ...s.activeTurn,
          toolCalls: s.activeTurn.toolCalls.map((tc) =>
            tc.toolCallId === evt.data.tool_call_id
              ? { ...tc, status: 'done' as const, result: evt.data.output_preview, durationMs: evt.data.duration_ms }
              : tc,
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
              : tc,
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
              : w,
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
            w.workerId === evt.data.worker_id ? { ...w, status: 'failed', error: evt.data.error } : w,
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
      const matched = s.hitlQueue.find((r) => r.requestId === evt.data.request_id)
      const toolName = matched?.tool ?? null
      const isAllowlist = evt.type === 'hitl.allowlisted'
      const autoApprovedTools = isAllowlist && toolName && !s.autoApprovedTools.includes(toolName)
        ? [...s.autoApprovedTools, toolName]
        : s.autoApprovedTools
      const now = new Date().toISOString()
      return {
        ...s,
        hitlQueue: remaining,
        status: remaining.length > 0 ? 'hitl' : 'running',
        autoApprovedTools,
        sessionUpdatedAt: now,
      }
    }

    case 'message.assistant': {
      const active = s.activeTurn
      if (!active) return s

      const turnTok = s.turnInputTokens + s.turnOutputTokens
      const completed: CompletedTurn = {
        id: active.id,
        userMessage: active.userMessage,
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
        sessionUpdatedAt: new Date().toISOString(),
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
      const m = evt.data.model
      const sessionModel = m != null && m !== '' ? m : (s.model ?? null)
      return {
        ...s,
        totalInputTokens: s.totalInputTokens + inTok,
        totalOutputTokens: s.totalOutputTokens + outTok,
        turnInputTokens: s.activeTurn ? s.turnInputTokens + inTok : s.turnInputTokens,
        turnOutputTokens: s.activeTurn ? s.turnOutputTokens + outTok : s.turnOutputTokens,
        model: sessionModel,
        metricsHistory: hist,
      }
    }

    case 'metric.cost': {
      const m = evt.data.model
      const sessionModel = m != null && m !== '' ? m : (s.model ?? null)
      return {
        ...s,
        totalCostUsd: s.totalCostUsd + evt.data.cost,
        model: sessionModel,
      }
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
        protocolNotes: pushProtocolNotes(s.protocolNotes, `Budget · exhausted ${evt.data.dimension}`),
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
        protocolNotes: pushProtocolNotes(s.protocolNotes, `Checkpoint restored · ${evt.data.thread}`),
      }

    case 'memory.session.write':
      return {
        ...s,
        memoryEnabled: true,
        protocolNotes: pushProtocolNotes(
          s.protocolNotes,
          `memory.session.write · ${evt.data.thread}${evt.data.turn_count != null ? ` · turns ${evt.data.turn_count}` : ''}`,
        ),
      }

    case 'memory.session.cleared':
      return {
        ...s,
        protocolNotes: pushProtocolNotes(s.protocolNotes, `memory.session.cleared · ${evt.data.thread}`),
      }

    case 'memory.session.turn_popped': {
      const turns = s.completedTurns
      const nextTurns = turns.length > 0 ? turns.slice(0, -1) : turns
      return {
        ...s,
        completedTurns: nextTurns,
        sessionUpdatedAt: new Date().toISOString(),
        protocolNotes: pushProtocolNotes(
          s.protocolNotes,
          `Undo · thread ${evt.data.thread} · ${evt.data.remaining_turns} turn(s) in session memory`,
        ),
      }
    }

    case 'memory.lt.recall':
      return {
        ...s,
        memoryEnabled: true,
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
        skillsEnabled: true,
        protocolNotes: pushProtocolNotes(
          s.protocolNotes,
          `Skill loaded · ${evt.data.skill_name}${evt.data.source ? ` (${evt.data.source})` : ''}`,
        ),
      }

    case 'skill.applied':
      return {
        ...s,
        skillsEnabled: true,
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
}
