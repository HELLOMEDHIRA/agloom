/** Unit tests for AGPBridge command serialization and initial state.
 * Process spawning is mocked — no Python runtime required.
 */

import { createAGPBridge } from '../runtime/bridge.js'
import { EventEmitter } from 'node:events'

// mock child_process

const mockWrite = jest.fn()
const mockStdin = { writable: true, write: mockWrite, on: jest.fn() }
const mockStdoutEmitter = new EventEmitter() as EventEmitter & { setEncoding: jest.Mock }
mockStdoutEmitter.setEncoding = jest.fn()
const mockStderrEmitter = new EventEmitter() as EventEmitter & { setEncoding: jest.Mock }
mockStderrEmitter.setEncoding = jest.fn()

const exitListeners: Array<(code: number | null, signal: NodeJS.Signals | null) => void> = []
const errorListeners: Array<(err: Error) => void> = []

type MockChild = {
  pid: number
  stdin: typeof mockStdin
  stdout: typeof mockStdoutEmitter
  stderr: typeof mockStderrEmitter
  on: jest.Mock
  kill: jest.Mock
}

const mockProc: MockChild = {
  pid: 12345,
  stdin: mockStdin,
  stdout: mockStdoutEmitter,
  stderr: mockStderrEmitter,
  on: jest.fn(),
  kill: jest.fn(),
}

mockProc.on.mockImplementation((event: string, fn: (...args: unknown[]) => void) => {
  if (event === 'exit') exitListeners.push(fn as (code: number | null, signal: NodeJS.Signals | null) => void)
  if (event === 'error') errorListeners.push(fn as (err: Error) => void)
  return mockProc
})

jest.mock('node:child_process', () => ({
  spawn: jest.fn(() => mockProc),
  execSync: jest.fn(),
}))

afterEach(() => {
  for (const fn of exitListeners.splice(0)) {
    fn(0, null)
  }
  errorListeners.length = 0
  mockProc.on.mockClear()
})

// helpers

const newBridge = () => {
  const bridge = createAGPBridge()
  bridge.start()
  return bridge
}

/** Minimal valid AGP v1 envelope (wire validation requires ``v`` + ``id``). */
const env = (overrides: Record<string, unknown> = {}) => ({
  v: '1',
  session: 's1',
  seq: 1,
  ts: '2026-01-01T00:00:00Z',
  id: 'evt_test_0000000000000001',
  ...overrides,
})

const lastWritten = (): Record<string, unknown> => {
  const calls = mockWrite.mock.calls
  const last = calls[calls.length - 1]?.[0] as string | undefined
  if (!last) throw new Error('No write calls recorded')
  return JSON.parse(last.trim())
}

// lifecycle

describe('AGPBridge — initial state', () => {
  it('starts with status "starting"', () => {
    const bridge = createAGPBridge()
    expect(bridge.status).toBe('starting')
  })

  it('pid is set after start()', () => {
    const bridge = newBridge()
    expect(bridge.pid).toBe(12345)
  })
})

// NDJSON stdout parsing

describe('AGPBridge — NDJSON parsing', () => {
  beforeEach(() => {
    mockWrite.mockClear()
  })

  it('emits typed event for a valid NDJSON line', (done) => {
    const bridge = newBridge()
    const payload = {
      ...env(),
      type: 'session.opened',
      data: { runtime_version: '0.1.0', protocol_version: '1' },
    }

    bridge.on('event', (evt) => {
      expect(evt.type).toBe('session.opened')
      done()
    })

    mockStdoutEmitter.emit('data', `${JSON.stringify(payload)  }\n`)
  })

  it('sets status to "ready" on session.opened', () => {
    const bridge = newBridge()
    const payload = {
      ...env(),
      type: 'session.opened',
      data: { runtime_version: '0.1.0', protocol_version: '1' },
    }
    mockStdoutEmitter.emit('data', `${JSON.stringify(payload)  }\n`)
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

    const line1 = JSON.stringify({ ...env({ seq: 1, id: 'evt_1' }), type: 'message.user', data: { content: 'hi' } })
    const line2 = JSON.stringify({ ...env({ seq: 2, id: 'evt_2' }), type: 'pattern.classified', data: { pattern: 'REACT' } })

    // Both lines arrive in a single data chunk
    mockStdoutEmitter.emit('data', `${line1  }\n${  line2  }\n`)
    expect(events).toHaveLength(2)
  })

  it('handles split chunks (partial lines)', () => {
    const bridge = newBridge()
    const events: unknown[] = []
    bridge.on('event', (e) => events.push(e))

    const full = JSON.stringify({ ...env(), type: 'message.user', data: { content: 'hi' } })
    const half = Math.floor(full.length / 2)

    // First chunk ends mid-line — no event yet
    mockStdoutEmitter.emit('data', full.slice(0, half))
    expect(events).toHaveLength(0)

    // Second chunk completes the line
    mockStdoutEmitter.emit('data', `${full.slice(half)  }\n`)
    expect(events).toHaveLength(1)
  })

  it('buffers stdout events until the first event listener, then delivers in order (resume replay race)', () => {
    const bridge = newBridge()
    const resumed = JSON.stringify({
      ...env({ seq: 1, id: 'evt_resume_0000000000000001' }),
      type: 'session.resumed',
      data: { runtime_version: '0.1.0', protocol_version: '1' },
    })
    const userMsg = JSON.stringify({
      ...env({ seq: 2, id: 'evt_user_00000000000000001' }),
      type: 'message.user',
      data: { content: 'prior turn' },
    })

    mockStdoutEmitter.emit('data', `${resumed  }\n${  userMsg  }\n`)
    expect(bridge.status).toBe('ready')

    const received: string[] = []
    bridge.on('event', (e) => received.push(e.type))

    expect(received).toEqual(['session.resumed', 'message.user'])
  })
})

// command methods

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

  it('memoryPopLastTurn() sends command.memory.pop_last_turn', () => {
    const bridge = newBridge()
    bridge.memoryPopLastTurn('thread-9')
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.memory.pop_last_turn')
    expect((cmd['data'] as Record<string, unknown>)['thread']).toBe('thread-9')
  })

  it('hitlRespond() sends command.hitl.respond', () => {
    const bridge = newBridge()
    bridge.hitlRespond('req-1', 'accept', 'looks good')
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.hitl.respond')
    expect((cmd['data'] as Record<string, unknown>)['request_id']).toBe('req-1')
    expect((cmd['data'] as Record<string, unknown>)['decision']).toBe('accept')
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

  it('harnessGit() sends command.harness.git', () => {
    const bridge = newBridge()
    bridge.harnessGit('diff', { path: 'src/a.ts', cached: true })
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.harness.git')
    const d = cmd['data'] as Record<string, unknown>
    expect(d['op']).toBe('diff')
    expect(d['path']).toBe('src/a.ts')
    expect(d['cached']).toBe(true)
  })

  it('planPreview() sends command.plan.preview', () => {
    const bridge = newBridge()
    bridge.planPreview('ship the feature')
    const cmd = lastWritten()
    expect(cmd['type']).toBe('command.plan.preview')
    expect((cmd['data'] as Record<string, unknown>)['prompt']).toBe('ship the feature')
  })

  it('send() is a no-op when stdin is not writable', () => {
    const bridge = newBridge()
    // Simulate stdin closing
    ;(mockStdin as Record<string, unknown>)['writable'] = false
    expect(() => bridge.invoke('test')).not.toThrow()
    ;(mockStdin as Record<string, unknown>)['writable'] = true
  })
})
