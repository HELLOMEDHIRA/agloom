/**
 * Unit tests for the web platform Zustand session store's `dispatch` reducer.
 * Tests cover: turn lifecycle, streaming, tools, workers, HITL,
 * execution trace, artifact extraction, and metrics.
 */

import { useSessionStore } from '../store/session'
import type { AGPEvent } from '../lib/agp/types'

// ── helpers ───────────────────────────────────────────────────────────────────

let _seq = 0
function env(overrides: Partial<Pick<AGPEvent, 'v' | 'session' | 'seq' | 'ts' | 'id'>> = {}): Pick<AGPEvent, 'v' | 'session' | 'seq' | 'ts' | 'id'> {
  const seq = ++_seq
  return {
    v: '1',
    session: 'ws-session',
    seq,
    ts: new Date().toISOString(),
    id: `evt-${seq.toString().padStart(8, '0')}`,
    ...overrides,
  }
}

function dispatch(evt: AGPEvent) {
  useSessionStore.getState().dispatch(evt)
}

function state() {
  return useSessionStore.getState()
}

beforeEach(() => {
  _seq = 0
  useSessionStore.getState().reset()
})

// ── session lifecycle ─────────────────────────────────────────────────────────

describe('session.opened', () => {
  it('records sessionId and runtimeVersion', () => {
    dispatch({ ...env(), type: 'session.opened', data: { runtime_version: '0.2.0', protocol_version: '1', capabilities: ['hitl'] } })
    expect(state().sessionId).toBe('ws-session')
    expect(state().runtimeVersion).toBe('0.2.0')
    expect(state().status).toBe('idle')
  })

  it('appends to execution trace', () => {
    dispatch({ ...env(), type: 'session.opened', data: { runtime_version: '0.2.0', protocol_version: '1', capabilities: [] } })
    expect(state().executionTrace).toHaveLength(1)
    expect(state().executionTrace[0]?.type).toBe('session.opened')
    expect(state().executionTrace[0]?.summary).toContain('0.2.0')
  })
})

describe('session.closed', () => {
  it('sets idle status on completed', () => {
    dispatch({ ...env(), type: 'session.closed', data: { reason: 'completed', duration_ms: 500 } })
    expect(state().status).toBe('idle')
    expect(state().activeTurn).toBeNull()
  })

  it('sets error status on error reason', () => {
    dispatch({ ...env(), type: 'session.closed', data: { reason: 'error', duration_ms: 0 } })
    expect(state().status).toBe('error')
  })
})

// ── turn lifecycle ────────────────────────────────────────────────────────────

describe('message.user', () => {
  it('opens an active turn', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'What is agloom?' } })
    const s = state()
    expect(s.activeTurn?.userMessage).toBe('What is agloom?')
    expect(s.status).toBe('running')
  })
})

describe('pattern.classified', () => {
  it('stores pattern in active turn', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'pattern.classified', data: { pattern: 'SUPERVISOR', complexity: 8 } })
    expect(state().activeTurn?.pattern).toBe('SUPERVISOR')
  })
})

describe('thinking.step', () => {
  it('appends thinking step and sets status thinking', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'thinking.step', data: { step: 'classify', label: 'Analyzing query', elapsed_ms: 120 } })
    expect(state().status).toBe('thinking')
    expect(state().activeTurn?.thinkingSteps).toHaveLength(1)
    expect(state().activeTurn?.thinkingSteps[0]?.elapsedMs).toBe(120)
  })
})

// ── streaming ─────────────────────────────────────────────────────────────────

describe('token.delta', () => {
  it('accumulates tokens without appending to trace', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    const traceBefore = state().executionTrace.length

    dispatch({ ...env(), type: 'token.delta', data: { text: 'Hello' } })
    dispatch({ ...env(), type: 'token.delta', data: { text: ' there' } })

    expect(state().activeTurn?.streamedTokens).toBe('Hello there')
    // token.delta must NOT be appended to execution trace (performance)
    expect(state().executionTrace.length).toBe(traceBefore)
  })
})

// ── tool calls ────────────────────────────────────────────────────────────────

describe('tool.call.start + tool.call.result + tool.call.error', () => {
  beforeEach(() => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
  })

  it('adds a pending tool call', () => {
    dispatch({ ...env(), type: 'tool.call.start', data: { tool_call_id: 'tc1', tool: 'search', args: { q: 'agloom' } } })
    expect(state().activeTurn?.toolCalls[0]?.status).toBe('pending')
  })

  it('resolves tool call to done', () => {
    dispatch({ ...env(), type: 'tool.call.start', data: { tool_call_id: 'tc1', tool: 'search', args: {} } })
    dispatch({ ...env(), type: 'tool.call.result', data: { tool_call_id: 'tc1', tool: 'search', output_preview: 'found it', duration_ms: 88 } })
    const tc = state().activeTurn?.toolCalls[0]
    expect(tc?.status).toBe('done')
    expect(tc?.durationMs).toBe(88)
  })

  it('resolves tool call to error on tool.call.error', () => {
    dispatch({ ...env(), type: 'tool.call.start', data: { tool_call_id: 'tc1', tool: 'bad', args: {} } })
    dispatch({ ...env(), type: 'tool.call.error', data: { tool_call_id: 'tc1', tool: 'bad', error: 'timeout' } })
    expect(state().activeTurn?.toolCalls[0]?.status).toBe('error')
  })
})

// ── workers ───────────────────────────────────────────────────────────────────

describe('worker events', () => {
  beforeEach(() => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
  })

  it('spawns a running worker', () => {
    dispatch({ ...env(), type: 'worker.spawned', data: { worker_id: 'w1', name: 'analyzer', pattern: 'REACT' } })
    expect(state().activeTurn?.workers[0]?.status).toBe('running')
    expect(state().activeTurn?.workers[0]?.name).toBe('analyzer')
  })

  it('marks worker done', () => {
    dispatch({ ...env(), type: 'worker.spawned', data: { worker_id: 'w1', name: 'analyzer' } })
    dispatch({ ...env(), type: 'worker.completed', data: { worker_id: 'w1', output_preview: 'analysis done' } })
    expect(state().activeTurn?.workers[0]?.status).toBe('done')
  })

  it('marks worker failed', () => {
    dispatch({ ...env(), type: 'worker.spawned', data: { worker_id: 'w1', name: 'analyzer' } })
    dispatch({ ...env(), type: 'worker.failed', data: { worker_id: 'w1', error: 'OOM' } })
    expect(state().activeTurn?.workers[0]?.status).toBe('failed')
    expect(state().activeTurn?.workers[0]?.error).toBe('OOM')
  })
})

// ── graph nodes ───────────────────────────────────────────────────────────────

describe('graph.node.enter', () => {
  it('tracks visited graph nodes', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'graph.node.enter', data: { node: 'classify' } })
    dispatch({ ...env(), type: 'graph.node.enter', data: { node: 'react' } })
    expect(state().activeTurn?.graphNodes.map((n) => n.nodeId)).toEqual(['classify', 'react'])
  })
})

// ── HITL ──────────────────────────────────────────────────────────────────────

describe('hitl lifecycle', () => {
  it('enqueues request and sets hitl status', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'hitl.request', data: { request_id: 'r1', kind: 'tool_approval', options: ['approve', 'reject'] } })
    expect(state().status).toBe('hitl')
    expect(state().hitlQueue).toHaveLength(1)
  })

  it('removes request on hitl.granted', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'hitl.request', data: { request_id: 'r1', kind: 'tool_approval', options: [] } })
    dispatch({ ...env(), type: 'hitl.granted', data: { request_id: 'r1', decision: 'accept' } })
    expect(state().hitlQueue).toHaveLength(0)
  })

  it('removes request on hitl.denied', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'hitl.request', data: { request_id: 'r1', kind: 'tool_approval', options: [] } })
    dispatch({ ...env(), type: 'hitl.denied', data: { request_id: 'r1', decision: 'reject' } })
    expect(state().hitlQueue).toHaveLength(0)
  })

  it('removes request on hitl.allowlisted', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'hitl.request', data: { request_id: 'r1', kind: 'tool_approval', options: [] } })
    dispatch({ ...env(), type: 'hitl.allowlisted', data: { request_id: 'r1', decision: 'allowlist' } })
    expect(state().hitlQueue).toHaveLength(0)
  })
})

// ── message.assistant — turn finalisation ─────────────────────────────────────

describe('message.assistant', () => {
  it('completes the turn and populates completedTurns', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'Hello' } })
    dispatch({ ...env(), type: 'message.assistant', data: { content: 'World', pattern: 'DIRECT' } })
    expect(state().completedTurns).toHaveLength(1)
    expect(state().completedTurns[0]?.assistantMessage).toBe('World')
    expect(state().activeTurn).toBeNull()
    expect(state().status).toBe('idle')
  })

  it('extracts code artifacts from assistant message', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    const content = '```python\nprint("hello world from agloom!")\n```'
    dispatch({ ...env(), type: 'message.assistant', data: { content, pattern: 'REACT' } })
    const completed = state().completedTurns[0]
    expect(completed?.artifacts).toHaveLength(1)
    expect(completed?.artifacts[0]?.type).toBe('code')
    expect(completed?.artifacts[0]?.language).toBe('python')
  })

  it('does not extract short code blocks as artifacts', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'message.assistant', data: { content: '```js\nok\n```', pattern: 'DIRECT' } })
    expect(state().completedTurns[0]?.artifacts).toHaveLength(0)
  })

  it('falls back to streamed tokens if content is empty', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'token.delta', data: { text: 'streamed' } })
    dispatch({ ...env(), type: 'message.assistant', data: { content: '', pattern: 'DIRECT' } })
    expect(state().completedTurns[0]?.assistantMessage).toBe('streamed')
  })
})

// ── execution trace ────────────────────────────────────────────────────────────

describe('execution trace', () => {
  it('accumulates non-token events in order', () => {
    dispatch({ ...env(), type: 'session.opened', data: { runtime_version: '0.1.0', protocol_version: '1', capabilities: [] } })
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'pattern.classified', data: { pattern: 'REACT', complexity: 4 } })
    expect(state().executionTrace.length).toBeGreaterThanOrEqual(3)
    const types = state().executionTrace.map((e) => e.type)
    expect(types).toContain('session.opened')
    expect(types).toContain('message.user')
    expect(types).toContain('pattern.classified')
  })
})

// ── metrics ───────────────────────────────────────────────────────────────────

describe('metric.tokens', () => {
  it('accumulates across multiple metric events', () => {
    dispatch({ ...env(), type: 'metric.tokens', data: { model: 'gpt-4o', input_tokens: 150, output_tokens: 60 } })
    dispatch({ ...env(), type: 'metric.tokens', data: { model: 'gpt-4o', input_tokens: 50, output_tokens: 40 } })
    expect(state().totalInputTokens).toBe(200)
    expect(state().totalOutputTokens).toBe(100)
    expect(state().model).toBe('gpt-4o')
  })
})

// ── errors ────────────────────────────────────────────────────────────────────

describe('error events', () => {
  it('error.fatal sets error status and message', () => {
    dispatch({ ...env(), type: 'error.fatal', data: { severity: 'fatal', message: 'Unhandled exception' } })
    expect(state().status).toBe('error')
    expect(state().errorMessage).toBe('Unhandled exception')
  })

  it('error.transient stores message without changing status', () => {
    dispatch({ ...env(), type: 'error.transient', data: { severity: 'transient', message: 'Retry in 1s', retryable: true } })
    expect(state().errorMessage).toBe('Retry in 1s')
    expect(state().status).toBe('idle')
  })
})

// ── connectionStatus ──────────────────────────────────────────────────────────

describe('setConnectionStatus', () => {
  it('updates connectionStatus independently', () => {
    useSessionStore.getState().setConnectionStatus('open')
    expect(state().connectionStatus).toBe('open')
    useSessionStore.getState().setConnectionStatus('error')
    expect(state().connectionStatus).toBe('error')
  })
})

// ── reset ─────────────────────────────────────────────────────────────────────

describe('reset', () => {
  it('wipes all mutable state', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'metric.tokens', data: { model: 'gpt-4o', input_tokens: 99, output_tokens: 33 } })
    useSessionStore.getState().reset()
    const s = state()
    expect(s.completedTurns).toHaveLength(0)
    expect(s.activeTurn).toBeNull()
    expect(s.executionTrace).toHaveLength(0)
    expect(s.totalInputTokens).toBe(0)
    expect(s.status).toBe('idle')
  })
})
