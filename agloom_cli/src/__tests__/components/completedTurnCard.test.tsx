/** Component tests: ``CompletedTurnCard`` (no session store). */

import React from 'react'
import { renderToString } from 'ink'
import { CompletedTurnCard } from '../../components/CompletedTurnCard.js'
import type { CompletedTurn } from '../../store/session.js'

describe('CompletedTurnCard (renderToString)', () => {
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
})
