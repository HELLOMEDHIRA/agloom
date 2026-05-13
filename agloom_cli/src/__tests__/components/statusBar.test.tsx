/** Component tests: ``StatusBar`` via Ink ``renderToString``. */

import React from 'react'
import { renderToString } from 'ink'
import { StatusBar } from '../../components/StatusBar.js'
import { useSessionStore } from '../../store/session.js'

describe('StatusBar (Ink renderToString)', () => {
  beforeEach(() => {
    useSessionStore.getState().reset()
  })

  afterEach(() => {
    useSessionStore.getState().reset()
  })

  it('shows thread id and IDLE when store is idle', () => {
    useSessionStore.setState({
      status: 'idle',
      sessionId: 'sess_integration_test',
    })
    // Wide layout so the status row is not clipped; thread label uses first 12 chars (see StatusBar).
    const frame = renderToString(<StatusBar thread="thread_abc123" layoutWidth={200} />, { columns: 240 })
    expect(frame).toMatch(/IDLE|idle/i)
    expect(frame).toContain('thread:thread_abc12')
    expect(frame).toContain('session:sess_integra')
  })

  it('shows HITL when the store is waiting on approval', () => {
    useSessionStore.setState({
      status: 'hitl',
      sessionId: null,
      hitlQueue: [
        {
          requestId: 'hr_1',
          kind: 'tool_approval',
          options: ['accept', 'reject'],
        },
      ],
    })
    const frame = renderToString(<StatusBar thread="t1" layoutWidth={90} />, { columns: 120 })
    expect(frame).toMatch(/HITL|hitl/i)
  })
})
