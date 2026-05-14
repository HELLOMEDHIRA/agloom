/** Component tests: ``CompletedTurnCard`` (uses session store for thinking expand). */

import React from 'react'
import { renderToString } from 'ink'
import { CompletedTurnCard } from '../../components/CompletedTurnCard.js'
import type { CompletedTurn } from '../../store/session.js'
import { useSessionStore } from '../../store/session.js'

describe('CompletedTurnCard (renderToString)', () => {
  beforeEach(() => {
    useSessionStore.getState().reset()
  })

  afterEach(() => {
    useSessionStore.getState().reset()
  })
  const baseTurn: CompletedTurn = {
    id: 'ct_1',
    userMessage: 'Say hello in one word.',
    assistantMessage: 'Hello.',
    thinkingSteps: [],
    toolCalls: [],
    workers: [],
    pattern: 'REACT',
    tokens: 42,
  }

  it('renders user message and assistant reply', () => {
    const frame = renderToString(<CompletedTurnCard turn={baseTurn} />, { columns: 100 })
    expect(frame).toContain('Say hello in one word.')
    expect(frame).toContain('Hello.')
    expect(frame).toContain('REACT')
    expect(frame).toContain('42')
  })

  it('collapses past thinking by default with a hint', () => {
    const turn: CompletedTurn = {
      ...baseTurn,
      thinkingSteps: [{ id: 's1', step: 'plan', label: 'Planning', detail: 'consider options' }],
    }
    const frame = renderToString(<CompletedTurnCard turn={turn} />, { columns: 100 })
    expect(frame).toContain('Thought · 1 step')
    expect(frame).toContain('Ctrl+Y')
    expect(frame).not.toContain('Planning')
  })

  it('shows thinking steps when expandHistoryThinking is on', () => {
    useSessionStore.setState({ expandHistoryThinking: true })
    const turn: CompletedTurn = {
      ...baseTurn,
      thinkingSteps: [{ id: 's1', step: 'plan', label: 'Planning', detail: 'consider options' }],
    }
    const frame = renderToString(<CompletedTurnCard turn={turn} />, { columns: 100 })
    expect(frame).toContain('Planning')
    expect(frame).toContain('consider options')
  })
})
