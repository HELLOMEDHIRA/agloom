/** Component tests: ``Header`` via ``renderToString`` (no live TTY; Jest-safe). */

import React from 'react'
import { renderToString } from 'ink'
import { Header } from '../../components/Header.js'
import { useSessionStore } from '../../store/session.js'

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

    const frame = renderToString(<Header layoutWidth={88} />, { columns: 120 })
    expect(frame).toContain('agloom')
    expect(frame).toContain('0.9.0')
    expect(frame).toContain('gpt-4o-mini')
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
    const frame = renderToString(<Header />, { columns: 100 })
    expect(frame).toContain('agloom')
    expect(frame).not.toContain('[')
  })
})
