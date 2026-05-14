/** Component tests: ``StatusBar`` via ``renderToString`` (no live TTY; Jest-safe). */

import React from 'react'
import { renderToString } from 'ink'
import { StatusBar } from '../../components/StatusBar.js'
import { InkUiProvider } from '../../components/InkUiProvider.js'
import { useSessionStore } from '../../store/session.js'

const renderStatus = (el: React.ReactElement, columns = 240) =>
  renderToString(<InkUiProvider>{el}</InkUiProvider>, { columns })

describe('StatusBar (renderToString)', () => {
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
    const frame = renderStatus(<StatusBar thread="thread_abc123" layoutWidth={200} />)
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
    const frame = renderStatus(<StatusBar thread="t1" layoutWidth={90} />, 120)
    expect(frame).toMatch(/HITL|hitl/i)
  })

  it('shows budget warning strip when budgetUi is approaching', () => {
    useSessionStore.setState({
      status: 'running',
      budgetUi: 'approaching',
    })
    const frame = renderStatus(<StatusBar thread="t1" layoutWidth={120} />, 160)
    expect(frame.toLowerCase()).toMatch(/budget|almost|exhaust/)
  })

  it('shows budget exhausted strip when budgetUi is exhausted', () => {
    useSessionStore.setState({
      status: 'error',
      budgetUi: 'exhausted',
    })
    const frame = renderStatus(<StatusBar thread="t1" layoutWidth={120} />, 160)
    expect(frame.toLowerCase()).toContain('exhaust')
  })
})
