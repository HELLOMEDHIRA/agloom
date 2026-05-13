/** React context contract for AGPClient. */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { AGPClientContext, createAGPClient, useAGPClient } from '../lib/agp/client'

const OriginalWebSocket = globalThis.WebSocket

class StubWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  readonly url = ''
  readyState = StubWebSocket.CONNECTING
  onopen: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  onclose: ((ev: CloseEvent) => void) | null = null
  constructor(_url: string | URL) {}
  send(): void {}
  close(): void {}
}

const Consumer = (): React.ReactElement => {
  const c = useAGPClient()
  return <span data-testid="st">{c.status}</span>
}

describe('useAGPClient', () => {
  beforeEach(() => {
    globalThis.WebSocket = StubWebSocket as unknown as typeof WebSocket
  })

  afterEach(() => {
    globalThis.WebSocket = OriginalWebSocket
  })

  it('throws when rendered outside AGPClientContext.Provider', () => {
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Consumer />)).toThrow(/useAGPClient must be used inside/)
    spy.mockRestore()
  })

  it('returns client from context', () => {
    const client = createAGPClient('ws://stub')
    render(
      <AGPClientContext.Provider value={client}>
        <Consumer />
      </AGPClientContext.Provider>,
    )
    expect(screen.getByTestId('st')).toHaveTextContent('closed')
  })
})
