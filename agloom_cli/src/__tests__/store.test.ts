/** Unit tests for the Zustand session store's `dispatch` reducer.
 * All AGP event branches are tested in isolation — no TUI rendering needed.
 */

import { useSessionStore } from '../store/session'
import type { AGPEvent } from '../types/agp'

// helpers

const env = (overrides: Partial<Pick<AGPEvent, 'v' | 'session' | 'seq' | 'ts' | 'id'>> = {}): Pick<AGPEvent, 'v' | 'session' | 'seq' | 'ts' | 'id'> => {
  return {
    v: '1',
    session: 'test-session',
    seq: 1,
    ts: new Date().toISOString(),
    id: '00000000000000000000000000000001',
    ...overrides,
  }
}

const dispatch = (evt: AGPEvent) => {
  useSessionStore.getState().dispatch(evt)
}

const state = () => {
  return useSessionStore.getState()
}

// reset between tests

beforeEach(() => {
  useSessionStore.getState().reset()
})

// session events

describe('session.opened', () => {
  it('sets sessionId and runtimeVersion', () => {
    dispatch({ ...env(), type: 'session.opened', data: { runtime_version: '0.1.0', protocol_version: '1' } })
    expect(state().sessionId).toBe('test-session')
    expect(state().runtimeVersion).toBe('0.1.0')
    expect(state().sessionOpenedAtMs).toEqual(expect.any(Number))
    expect(state().status).toBe('idle')
  })
})

describe('session.closed', () => {
  it('sets status idle on completed', () => {
    dispatch({ ...env(), type: 'session.closed', data: { reason: 'completed', duration_ms: 100 } })
    expect(state().status).toBe('idle')
    expect(state().activeTurn).toBeNull()
  })

  it('sets status error on error reason', () => {
    dispatch({ ...env(), type: 'session.closed', data: { reason: 'error', duration_ms: 0, error: 'timeout' } })
    expect(state().status).toBe('error')
  })
})

// turn lifecycle

describe('message.user', () => {
  it('creates an activeTurn with the user message', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'Hello, world' } })
    const s = state()
    expect(s.activeTurn).not.toBeNull()
    expect(s.activeTurn?.userMessage).toBe('Hello, world')
    expect(s.status).toBe('running')
    expect(s.hitlQueue).toHaveLength(0)
  })
})

describe('pattern.classified', () => {
  it('sets pattern on active turn', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'test' } })
    dispatch({ ...env(), type: 'pattern.classified', data: { pattern: 'REACT', complexity: 5 } })
    expect(state().activeTurn?.pattern).toBe('REACT')
  })

  it('is a no-op when no active turn', () => {
    dispatch({ ...env(), type: 'pattern.classified', data: { pattern: 'REACT' } })
    expect(state().activeTurn).toBeNull()
  })
})

// streaming tokens

describe('token.delta', () => {
  it('accumulates streamed tokens', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'token.delta', data: { text: 'Hello' } })
    dispatch({ ...env(), type: 'token.delta', data: { text: ' world' } })
    expect(state().activeTurn?.streamedTokens).toBe('Hello world')
  })

  it('is a no-op without active turn', () => {
    dispatch({ ...env(), type: 'token.delta', data: { text: 'x' } })
    expect(state().activeTurn).toBeNull()
  })
})

// tool calls

describe('tool.call.start + tool.call.result + tool.call.error', () => {
  it('adds a pending tool call', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'tool.call.start', data: { tool_call_id: 'tc1', tool: 'web_search', args: { query: 'test' } } })
    const tc = state().activeTurn?.toolCalls[0]
    expect(tc?.tool).toBe('web_search')
    expect(tc?.status).toBe('pending')
  })

  it('marks the tool call done when result arrives', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'tool.call.start', data: { tool_call_id: 'tc1', tool: 'web_search', args: {} } })
    dispatch({ ...env(), type: 'tool.call.result', data: { tool_call_id: 'tc1', tool: 'web_search', output_preview: 'ok', duration_ms: 42 } })
    const tc = state().activeTurn?.toolCalls[0]
    expect(tc?.status).toBe('done')
    expect(tc?.result).toBe('ok')
    expect(tc?.durationMs).toBe(42)
  })

  it('marks the tool call as error on tool.call.error', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'tool.call.start', data: { tool_call_id: 'tc2', tool: 'bad_tool', args: {} } })
    dispatch({ ...env(), type: 'tool.call.error', data: { tool_call_id: 'tc2', tool: 'bad_tool', error: 'failed' } })
    const tc = state().activeTurn?.toolCalls[0]
    expect(tc?.status).toBe('error')
    expect(tc?.error).toBe('failed')
  })
})

// workers

describe('worker.spawned / worker.completed / worker.failed', () => {
  beforeEach(() => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
  })

  it('adds a running worker', () => {
    dispatch({ ...env(), type: 'worker.spawned', data: { worker_id: 'w1', name: 'researcher', pattern: 'REACT', task: 'gather facts' } })
    const w = state().activeTurn?.workers[0]
    expect(w?.workerId).toBe('w1')
    expect(w?.status).toBe('running')
  })

  it('marks worker done on worker.completed', () => {
    dispatch({ ...env(), type: 'worker.spawned', data: { worker_id: 'w1', name: 'researcher' } })
    dispatch({ ...env(), type: 'worker.completed', data: { worker_id: 'w1', output_preview: 'result' } })
    expect(state().activeTurn?.workers[0]?.status).toBe('done')
    expect(state().activeTurn?.workers[0]?.outputPreview).toBe('result')
  })

  it('marks worker failed on worker.failed', () => {
    dispatch({ ...env(), type: 'worker.spawned', data: { worker_id: 'w1', name: 'researcher' } })
    dispatch({ ...env(), type: 'worker.failed', data: { worker_id: 'w1', error: 'network error' } })
    expect(state().activeTurn?.workers[0]?.status).toBe('failed')
    expect(state().activeTurn?.workers[0]?.error).toBe('network error')
  })
})

// HITL

describe('hitl lifecycle', () => {
  it('enqueues a HITL request and sets status hitl', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'hitl.request', data: { request_id: 'r1', kind: 'tool_approval', options: ['approve', 'reject'] } })
    expect(state().status).toBe('hitl')
    expect(state().hitlQueue).toHaveLength(1)
    expect(state().hitlQueue[0]?.requestId).toBe('r1')
  })

  it('removes request from queue on hitl.granted', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'hitl.request', data: { request_id: 'r1', kind: 'tool_approval', options: ['approve'] } })
    dispatch({ ...env(), type: 'hitl.granted', data: { request_id: 'r1', decision: 'accept' } })
    expect(state().hitlQueue).toHaveLength(0)
    expect(state().status).toBe('running')
  })

  it('removes request from queue on hitl.denied', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'hitl.request', data: { request_id: 'r1', kind: 'tool_approval', options: ['approve'] } })
    dispatch({ ...env(), type: 'hitl.denied', data: { request_id: 'r1', decision: 'reject' } })
    expect(state().hitlQueue).toHaveLength(0)
  })

  it('removes request from queue on hitl.allowlisted', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'hitl.request', data: { request_id: 'r1', kind: 'tool_approval', options: ['approve'] } })
    dispatch({ ...env(), type: 'hitl.allowlisted', data: { request_id: 'r1', decision: 'allowlist' } })
    expect(state().hitlQueue).toHaveLength(0)
  })
})

// message.assistant — turn completion

describe('message.assistant', () => {
  it('caps completedTurns length for long sessions', () => {
    const n = 205
    for (let i = 0; i < n; i++) {
      dispatch({ ...env({ seq: i * 2 + 1 }), type: 'message.user', data: { content: `u${i}` } })
      dispatch({
        ...env({ seq: i * 2 + 2 }),
        type: 'message.assistant',
        data: { content: `a${i}`, pattern: 'DIRECT' },
      })
    }
    expect(state().completedTurns).toHaveLength(200)
    expect(state().completedTurns[0]?.userMessage).toBe('u5')
    expect(state().completedTurns[199]?.userMessage).toBe('u204')
  })

  it('moves active turn to completedTurns', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'Hello' } })
    dispatch({ ...env(), type: 'token.delta', data: { text: 'Hi' } })
    dispatch({ ...env(), type: 'message.assistant', data: { content: 'Hi there!', pattern: 'DIRECT' } })

    const s = state()
    expect(s.activeTurn).toBeNull()
    expect(s.completedTurns).toHaveLength(1)
    expect(s.completedTurns[0]?.assistantMessage).toBe('Hi there!')
    expect(s.completedTurns[0]?.pattern).toBe('DIRECT')
    expect(s.status).toBe('idle')
  })

  it('falls back to streamed tokens if content is empty', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'token.delta', data: { text: 'streamed answer' } })
    dispatch({ ...env(), type: 'message.assistant', data: { content: '', pattern: 'DIRECT' } })
    expect(state().completedTurns[0]?.assistantMessage).toBe('streamed answer')
  })
})

// metrics

describe('metric.tokens', () => {
  it('accumulates total token counts', () => {
    dispatch({ ...env(), type: 'metric.tokens', data: { model: 'gpt-4', input_tokens: 100, output_tokens: 50 } })
    dispatch({ ...env(), type: 'metric.tokens', data: { model: 'gpt-4', input_tokens: 200, output_tokens: 80 } })
    expect(state().totalInputTokens).toBe(300)
    expect(state().totalOutputTokens).toBe(130)
    expect(state().model).toBe('gpt-4')
    expect(state().metricsHistory).toHaveLength(2)
    expect(state().metricsHistory[1]?.phase).toBeUndefined()
  })

  it('attributes tokens to the active turn and rolls into completedTurn.tokens', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'metric.tokens', data: { phase: 'react', input_tokens: 10, output_tokens: 5 } })
    expect(state().turnInputTokens).toBe(10)
    expect(state().turnOutputTokens).toBe(5)
    dispatch({ ...env(), type: 'message.assistant', data: { content: 'done', pattern: 'DIRECT' } })
    expect(state().completedTurns[0]?.tokens).toBe(15)
    expect(state().turnInputTokens).toBe(0)
  })
})

describe('metric.cost', () => {
  it('accumulates USD estimate', () => {
    dispatch({ ...env(), type: 'metric.cost', data: { cost: 0.002, currency: 'USD', model: 'x' } })
    dispatch({ ...env(), type: 'metric.cost', data: { cost: 0.001 } })
    expect(state().totalCostUsd).toBeCloseTo(0.003, 6)
  })
})

// errors

describe('error events', () => {
  it('error.fatal sets error status', () => {
    dispatch({ ...env(), type: 'error.fatal', data: { severity: 'fatal', message: 'Runtime crashed' } })
    expect(state().status).toBe('error')
    expect(state().errorMessage).toBe('Runtime crashed')
  })

  it('error.transient sets errorMessage but keeps status', () => {
    dispatch({ ...env(), type: 'error.transient', data: { severity: 'transient', message: 'Rate limited', retryable: true } })
    expect(state().errorMessage).toBe('Rate limited')
  })
})

// graph.node.enter

describe('graph.node.enter', () => {
  it('appends the node name to activeTurn.graphNodes', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'graph.node.enter', data: { node: 'classify' } })
    dispatch({ ...env(), type: 'graph.node.enter', data: { node: 'react' } })
    expect(state().activeTurn?.graphNodes).toEqual(['classify', 'react'])
  })
})

// reset

describe('reset', () => {
  it('clears all mutable state', () => {
    dispatch({ ...env(), type: 'message.user', data: { content: 'q' } })
    dispatch({ ...env(), type: 'metric.tokens', data: { model: 'gpt-4', input_tokens: 50, output_tokens: 20 } })
    dispatch({ ...env(), type: 'metric.cost', data: { cost: 0.01 } })
    dispatch({ ...env(), type: 'runtime.config', data: { model_id: 'x', tool_names: ['a'], capabilities: [] } })
    useSessionStore.getState().appendProtocolNote('manual note')
    useSessionStore.getState().reset()
    const s = state()
    expect(s.completedTurns).toHaveLength(0)
    expect(s.activeTurn).toBeNull()
    expect(s.totalInputTokens).toBe(0)
    expect(s.metricsHistory).toHaveLength(0)
    expect(s.totalCostUsd).toBe(0)
    expect(s.status).toBe('idle')
    expect(s.protocolNotes).toHaveLength(0)
    expect(s.toolNames).toBeNull()
  })
})

describe('runtime.config', () => {
  it('updates model, toolNames, and protocol notes', () => {
    dispatch({
      ...env(),
      type: 'runtime.config',
      data: { model_id: 'gpt-4o', tool_names: ['read_file'], capabilities: ['hitl'] },
    })
    const s = state()
    expect(s.model).toBe('gpt-4o')
    expect(s.toolNames).toEqual(['read_file'])
    expect(s.capabilities).toEqual(['hitl'])
    expect(s.protocolNotes.some((n) => n.includes('runtime.config'))).toBe(true)
  })
})

describe('feedback.scored', () => {
  it('appends a wire note', () => {
    dispatch({
      ...env(),
      type: 'feedback.scored',
      data: { run_id: 'run_abcdef123456', rating: '5', comment: 'ok' },
    })
    expect(state().protocolNotes.some((n) => n.includes('Feedback scored'))).toBe(true)
  })
})

describe('graph.node.exit', () => {
  it('records a protocol note', () => {
    dispatch({ ...env(), type: 'graph.node.exit', data: { node: 'react', duration_ms: 120 } })
    expect(state().protocolNotes.some((n) => n.includes('Graph exit'))).toBe(true)
  })
})
