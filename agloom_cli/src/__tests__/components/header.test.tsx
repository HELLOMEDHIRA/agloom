/** Component tests: ``Header`` via ``renderToString`` (no live TTY; Jest-safe). */

import React from 'react'
import { renderToString } from 'ink'
import { Header } from '../../components/Header.js'
import { InkUiProvider } from '../../components/InkUiProvider.js'
import { useSessionStore } from '../../store/session.js'

const renderHeader = (el: React.ReactElement, columns = 120) =>
  renderToString(<InkUiProvider>{el}</InkUiProvider>, { columns })

describe('Header (renderToString)', () => {
  beforeEach(() => {
    useSessionStore.getState().reset()
  })

  afterEach(() => {
    useSessionStore.getState().reset()
  })

  it('renders brand, version, model, pattern, and tokens from the session store', () => {
    useSessionStore.setState({
      runtimeVersion: '0.9.0',
      model: 'openai:gpt-4o-mini',
      totalInputTokens: 1024,
      totalOutputTokens: 256,
      activeTurn: {
        id: 'turn_1',
        userMessage: 'ping',
        thinkingSteps: [],
        toolCalls: [],
        workers: [],
        streamedTokens: '',
        pattern: 'REACT',
        graphNodes: [],
      },
    })

    const frame = renderHeader(<Header layoutWidth={88} />)
    const lower = frame.toLowerCase()
    expect(lower).toContain('agloom')
    expect(frame).toContain('0.9.0')
    expect(lower).toContain('gpt-4o-mini')
    expect(frame).toContain('REACT')
    expect(frame).toMatch(/↑/)
    expect(frame).toMatch(/↓/)
  })

  it('renders without model/pattern when unset', () => {
    useSessionStore.setState({
      runtimeVersion: null,
      model: null,
      totalInputTokens: 0,
      totalOutputTokens: 0,
      activeTurn: null,
    })
    const frame = renderHeader(<Header />, 100)
    expect(frame.toLowerCase()).toContain('agloom')
    expect(frame.toLowerCase()).not.toContain('gpt-4o')
  })
})
