/**
 * Unit tests for createAGPClient — WebSocket lifecycle, message dispatch, reconnect scheduling.
 * Uses a MockWebSocket implementation (no real network).
 */

import { createAGPClient } from '../lib/agp/client'

const CONNECTING = 0
const OPEN = 1
const CLOSED = 3

const mockSocketInstances: MockWebSocket[] = []

/** Minimal WebSocket double for Jest (open completes on next microtask). */
class MockWebSocket {
  static readonly CONNECTING = CONNECTING
  static readonly OPEN = OPEN
  static readonly CLOSING = 2
  static readonly CLOSED = CLOSED

  readonly url: string
  readyState = CONNECTING
  onopen: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent<string>) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  onclose: ((ev: CloseEvent) => void) | null = null
  readonly sent: string[] = []

  constructor(url: string | URL) {
    this.url = typeof url === 'string' ? url : url.toString()
    mockSocketInstances.push(this)
    queueMicrotask(() => {
      if (this.readyState !== CLOSED) {
        this.readyState = OPEN
        this.onopen?.(new Event('open'))
      }
    })
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(code = 1000, reason = ''): void {
    this.simulateClose(code, reason)
  }

  /** Simulate server / transport close. */
  simulateClose(code = 1000, reason = ''): void {
    this.readyState = CLOSED
    this.onclose?.({ code, reason } as CloseEvent)
  }

  /** Deliver an inbound frame as if from the runtime. */
  simulateMessage(data: string): void {
    this.onmessage?.({ data } as MessageEvent<string>)
  }
}

const OriginalWebSocket = globalThis.WebSocket

const installMockWs = (): void => {
  mockSocketInstances.length = 0
  globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket
}

const restoreWebSocket = (): void => {
  globalThis.WebSocket = OriginalWebSocket
}

const flushMicrotasks = async (): Promise<void> => {
  await Promise.resolve()
}

describe('createAGPClient', () => {
  beforeEach(() => {
    installMockWs()
    jest.spyOn(Math, 'random').mockReturnValue(0)
  })

  afterEach(() => {
    jest.useRealTimers()
    jest.restoreAllMocks()
    restoreWebSocket()
  })

  it('starts closed until connect()', () => {
    const client = createAGPClient('ws://example.test/agp', 100)
    expect(client.status).toBe('closed')
    expect(mockSocketInstances).toHaveLength(0)
  })

  it('connect opens WebSocket and reaches open status', async () => {
    const client = createAGPClient('ws://example.test/agp', 100)
    const statuses: string[] = []
    client.onStatus((s) => {
      statuses.push(s)
    })
    client.connect()
    expect(mockSocketInstances).toHaveLength(1)
    expect(mockSocketInstances[0]?.url).toBe('ws://example.test/agp')
    expect(client.status).toBe('connecting')
    await flushMicrotasks()
    expect(client.status).toBe('open')
    expect(statuses).toContain('connecting')
    expect(statuses).toContain('open')
  })

  it('invokes onEvent with parsed AGP envelopes', async () => {
    const client = createAGPClient('ws://example.test/agp', 100)
    client.connect()
    await flushMicrotasks()
    const received: unknown[] = []
    client.onEvent((e) => {
      received.push(e)
    })
    const evt = {
      v: '1',
      session: 's1',
      seq: 1,
      ts: new Date().toISOString(),
      id: '01hzxxxxxxxxxxxxxxxxxxxxxxxxxx',
      type: 'session.opened',
      data: { runtime_version: '0.1.0', protocol_version: '1' },
    }
    mockSocketInstances[0]?.simulateMessage(JSON.stringify(evt))
    expect(received).toHaveLength(1)
    expect((received[0] as { type: string }).type).toBe('session.opened')
  })

  it('emits diagnostic on malformed JSON frames', async () => {
    const client = createAGPClient('ws://example.test/agp', 100)
    client.connect()
    await flushMicrotasks()
    const lines: string[] = []
    client.onDiagnostic((l) => {
      lines.push(l)
    })
    mockSocketInstances[0]?.simulateMessage('not-json{')
    expect(lines.some((l) => l.includes('non-JSON'))).toBe(true)
  })

  it('send serializes commands only when socket is OPEN', async () => {
    const client = createAGPClient('ws://example.test/agp', 100)
    client.send({ type: 'command.ping', data: {} })
    expect(mockSocketInstances).toHaveLength(0)

    client.connect()
    await flushMicrotasks()
    client.send({ type: 'command.ping', data: {} })
    expect(mockSocketInstances[0]?.sent).toHaveLength(1)
    expect(JSON.parse(mockSocketInstances[0]?.sent[0] ?? '{}')).toMatchObject({ type: 'command.ping' })
  })

  it('invoke maps to command.invoke', async () => {
    const client = createAGPClient('ws://example.test/agp', 100)
    client.connect()
    await flushMicrotasks()
    client.invoke('hello', 'thread-a')
    expect(JSON.parse(mockSocketInstances[0]?.sent[0] ?? '{}')).toEqual({
      type: 'command.invoke',
      data: { prompt: 'hello', thread: 'thread-a' },
    })
  })

  it('disconnect clears reconnect and closes socket', async () => {
    const client = createAGPClient('ws://example.test/agp', 100)
    client.connect()
    await flushMicrotasks()
    client.disconnect()
    expect(client.status).toBe('closed')
    mockSocketInstances[0]?.simulateClose()
    jest.useFakeTimers()
    jest.advanceTimersByTime(60_000)
    expect(mockSocketInstances).toHaveLength(1)
  })

  it('schedules reconnect with backoff after abnormal close when still connected', async () => {
    jest.useFakeTimers({ advanceTimers: true })
    const client = createAGPClient('ws://example.test/agp', 2000)
    client.connect()
    await flushMicrotasks()
    expect(mockSocketInstances).toHaveLength(1)

    mockSocketInstances[0]?.simulateClose(1006, 'abnormal')
    expect(client.status).toBe('connecting')

    jest.advanceTimersByTime(2000)
    await flushMicrotasks()
    expect(mockSocketInstances.length).toBeGreaterThanOrEqual(2)
    expect(mockSocketInstances[1]?.url).toBe('ws://example.test/agp')
  })
})
