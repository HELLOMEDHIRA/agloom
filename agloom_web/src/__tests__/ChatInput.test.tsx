/**
 * Component test — ChatInput integrates Zustand; verifies submit wiring.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ChatInput } from '../components/chat/ChatInput'
import { useSessionStore } from '../store/session'

describe('ChatInput', () => {
  beforeEach(() => {
    useSessionStore.getState().reset()
  })

  it('calls onSubmit with trimmed text on Enter', async () => {
    const user = userEvent.setup()
    const onSubmit = jest.fn()
    const onCancel = jest.fn()
    render(<ChatInput onSubmit={onSubmit} onCancel={onCancel} />)

    const ta = screen.getByPlaceholderText(/message agloom/i)
    await user.type(ta, 'hello world')
    await user.keyboard('{Enter}')

    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(onSubmit).toHaveBeenCalledWith('hello world')
    expect(ta).toHaveValue('')
  })

  it('shows cancel control when isRunning', async () => {
    const user = userEvent.setup()
    const onSubmit = jest.fn()
    const onCancel = jest.fn()
    render(<ChatInput onSubmit={onSubmit} onCancel={onCancel} isRunning />)

    await user.click(screen.getByTitle(/cancel/i))
    expect(onCancel).toHaveBeenCalled()
  })

  it('shows token footer when store reports usage', () => {
    useSessionStore.setState({
      totalInputTokens: 1200,
      totalOutputTokens: 800,
      model: 'test-model',
    })
    render(<ChatInput onSubmit={jest.fn()} onCancel={jest.fn()} />)
    expect(screen.getByText('test-model')).toBeInTheDocument()
    expect(screen.getByText(/↑.*↓/)).toBeInTheDocument()
  })
})
