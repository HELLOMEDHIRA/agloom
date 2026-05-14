/** Component tests: ``CompletedTurnCard`` (thinking expand via prop for memo correctness). */

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
    const frame = renderToString(<CompletedTurnCard turn={baseTurn} thinkingExpanded={false} />, { columns: 100 })
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
    const frame = renderToString(<CompletedTurnCard turn={turn} thinkingExpanded={false} />, { columns: 100 })
    expect(frame).toContain('Thought · 1 step')
    expect(frame).toContain('Ctrl+Y')
    expect(frame).toContain('/think')
    expect(frame).not.toContain('Planning')
  })

  it('shows thinking steps when thinkingExpanded is true', () => {
    const turn: CompletedTurn = {
      ...baseTurn,
      thinkingSteps: [{ id: 's1', step: 'plan', label: 'Planning', detail: 'consider options' }],
    }
    const frame = renderToString(<CompletedTurnCard turn={turn} thinkingExpanded />, { columns: 100 })
    expect(frame).toContain('Planning')
    expect(frame).toContain('consider options')
  })

  it('expands read_file tool output by default (preserve newlines)', () => {
    useSessionStore.setState({ toolCallExpandedById: {} })
    const turn: CompletedTurn = {
      ...baseTurn,
      toolCalls: [
        {
          id: 'tc1',
          toolCallId: 'call_1',
          tool: 'read_file',
          args: { path: 'pyproject.toml' },
          status: 'done',
          result: 'line_a\nline_b\nline_c',
        },
      ],
    }
    const frame = renderToString(<CompletedTurnCard turn={turn} thinkingExpanded={false} />, { columns: 100 })
    expect(frame).toContain('line_a')
    expect(frame).toContain('line_b')
    expect(frame).toContain('line_c')
  })
})
