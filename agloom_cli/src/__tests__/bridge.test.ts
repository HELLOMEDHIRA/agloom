/**
 * Unit tests for AGPBridge command serialization and initial state.
 * Process spawning is mocked — no Python runtime required.
 */

import { AGPBridge } from '../runtime/bridge'
import { EventEmitter } from 'node:events'

// ── mock child_process ────────────────────────────────────────────────────────

const mockWrite = jest.fn()
const mockStdin = { writable: true, write: mockWrite }
const mockStdoutEmitter = new EventEmitter() as EventEmitter & { setEncoding: jest.Mock }
mockStdoutEmitter.setEncoding = jest.fn()
mockStdoutEmitter.setMaxListeners(50)
const mockStderrEmitter = new EventEmitter() as EventEmitter & { setEncoding: jest.Mock }
mockStderrEmitter.setEncoding = jest.fn()
mockStderrEmitter.setMaxListeners(50)

const mockProc = {
  pid: 12345,
  stdin: mockStdin,
  stdout: mockStdoutEmitter,
  stderr: mockStderrEmitter,
  on: jest.fn(),
  kill: jest.fn(),
}

jest.mock('node:child_process', () => ({
  spawn: jest.fn(() => mockProc),
}))

// ── helpers ───────────────────────────────────────────────────────────────────

function newBridge() {
  const bridge = new AGPBridge()
  bridge.start()
  return bridge
}

function lastWritten(): Record<string, unknown> {
  const calls = mockWrite.mock.calls
  const last = calls[calls.length - 1]?.[0] as string | undefined
  if (!last) throw new Error('No write calls recorded')
  return JSON.parse(last.trim())
}

// ── lifecycle ─────────────────────────────────────────────────────────────────

describe('AGPBridge — initial state', () => {
  it('starts with status "starting"', () => {
    const bridge = new AGPBridge()
    expect(bridge.status).toBe('starting')
  })

  it('pid is set after start()', () => {
    const bridge = newBridge()
    expect(bridge.pid).toBe(12345)
  })
})

// ── NDJSON stdout parsing ─────────────────────────────────────────────────────

describe('AGPBridge — NDJSON parsing', () => {
  beforeEach(() => {
    mockWrite.mockClear()
  })

  it('emits typed event for a valid NDJSON line', (done) => {
    const bridge = newBridge()
    const payload = { type: 'session.opened', session: 's1', seq: 1, ts: '2026-01-01T00:00:00Z', data: { runtime_version: '0.1.0', protocol_version: '1', capabilities: [] } }

    bridge.on('event', (evt) => {
      expect(evt.type).toBe('session.opened')
      done()
    })

    mockStdoutEmitter.emit('data', JSON.stringify(payload) + '\n')
  })

  it('sets status to "ready" on session.opened', () => {
    const bridge = newBridge()
    const payload = { type: 'session.opened', session: 's1', seq: 1, ts: '2026-01-01T00:00:00Z', data: { runtime_version: '0.1.0', protocol_version: '1', capabilities: [] } }
    mockStdoutEmitter.emit('data', JSON.stringify(payload) + '\n')
    expect(bridge.status).toBe('ready')
  })

  it('emits diagnostic for non-JSON stdout lines', (done) => {
    const bridge = newBridge()
    bridge.on('diagnostic', (line) => {
      expect(line).toContain('[stdout]')
      done()
    })
    mockStdoutEmitter.emit('data', 'not json at all\n')
  })

  it('handles multi-line chunks (buffer splitting)', () => {
    const bridge = newBridge()
    const events: unknown[] = []
    bridge.on('event', (e) => events.push(e))

    const line1 = JSON.stringify({ type: 'message.user', session: 's1', seq: 1, ts: '2026-01-01T00:00:00Z', data: { content: 'hi' } })
    const line2 = JSON.stringify({ type: 'pattern.classified', session: 's1', seq: 2, ts: '2026-01-01T00:00:00Z', data: { pattern: 'REACT' } })

    // Both lines arrive in a single data chunk
    mockStdoutEmitter.emit('data', line1 + '\n' + line2 + '\n')
    expect(events).toHaveLength(2)
  })

  it('handles split chunks (partial lines)', () => {
    const bridge = newBridge()
    const events: unknown[] = []
    bridge.on('event', (e) => events.push(e))

    const full = JSON.stringify({ type: 'message.user', session: 's1', seq: 1, ts: '2026-01-01T00:00:00Z', data: { content: 'hi' } })
    const half = Math.floor(full.length / 2)

    // First chunk ends mid-line — no event yet
    mockStdoutEmitter.emit('data', full.slice(0, half))
    expect(events).toHaveLength(0)

    // Second chunk completes the line
    mockStdoutEmitter.emit('data', full.slice(half) + '\n')
    expect(events).toHaveLength(1)
  })
})

// ── command methods ────────────────────────────────────────────────────────────

describe('AGPBridge — command dispatch', () => {
  beforeEach(() => {
    mockWrite.mockClear()
  })

  it('invoke() sends command.invoke with prompt', () => {
    const bridge = newBridge()
    bridge.invoke('Hello agent', 'thread-1')
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.invoke')
    expect((cmd['data'] as Record<string, unknown>)['prompt']).toBe('Hello agent')
    expect((cmd['data'] as Record<string, unknown>)['thread']).toBe('thread-1')
  })

  it('cancel() sends command.cancel', () => {
    const bridge = newBridge()
    bridge.cancel('thread-1')
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.cancel')
  })

  it('hitlRespond() sends command.hitl.respond', () => {
    const bridge = newBridge()
    bridge.hitlRespond('req-1', 'approve', 'looks good')
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.hitl.respond')
    expect((cmd['data'] as Record<string, unknown>)['request_id']).toBe('req-1')
    expect((cmd['data'] as Record<string, unknown>)['decision']).toBe('approve')
  })

  it('feedback() sends command.feedback', () => {
    const bridge = newBridge()
    bridge.feedback('run-abc', '5', 'Great!')
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.feedback')
    expect((cmd['data'] as Record<string, unknown>)['run_id']).toBe('run-abc')
    expect((cmd['data'] as Record<string, unknown>)['rating']).toBe('5')
  })

  it('shutdown() sends command.runtime.shutdown', () => {
    const bridge = newBridge()
    bridge.shutdown()
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.runtime.shutdown')
  })

  it('send() is a no-op when stdin is not writable', () => {
    const bridge = newBridge()
    // Simulate stdin closing
    ;(mockStdin as Record<string, unknown>)['writable'] = false
    expect(() => bridge.invoke('test')).not.toThrow()
    ;(mockStdin as Record<string, unknown>)['writable'] = true
  })
})
