/** InputBar history suggestion highlight + hint line. */

import React from 'react'
import { renderToString } from 'ink'
import { InputBar } from '../../components/InputBar.js'
import { InkUiProvider } from '../../components/InkUiProvider.js'
import { useSessionStore } from '../../store/session.js'

const renderBar = (el: React.ReactElement, columns = 100) =>
  renderToString(<InkUiProvider>{el}</InkUiProvider>, { columns })

describe('InputBar suggestions', () => {
  beforeEach(() => {
    useSessionStore.getState().reset()
  })

  afterEach(() => {
    useSessionStore.getState().reset()
  })

  it('renders highlighted suggestion row and pick hint', () => {
    const frame = renderBar(
      <InputBar
        value="can you"
        onChange={() => {}}
        onSubmit={() => {}}
        suggestions={['can you please read pyproject', 'can you help']}
        composerWidth={80}
      />,
    )
    expect(frame).toContain('▸')
    expect(frame).toContain('can you please')
    expect(frame).toContain('↑↓ select')
    expect(frame).toContain('Tab apply')
  })
})
