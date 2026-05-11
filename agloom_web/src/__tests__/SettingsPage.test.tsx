/**
 * Settings route — wrapped with AGP client + theme providers.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AGPClientContext } from '../lib/agp/client.js'
import type { AGPClient } from '../lib/agp/client.js'
import { ThemeProvider } from '../lib/theme.js'
import { SettingsPage } from '../routes/SettingsPage.js'

describe('SettingsPage', () => {
  it('renders settings heading and WebSocket URL docs', () => {
    const mockClient = {
      send: jest.fn(),
      status: 'closed' as const,
      connect: jest.fn(),
      disconnect: jest.fn(),
      onEvent: jest.fn(() => jest.fn()),
      onStatus: jest.fn(() => jest.fn()),
      onDiagnostic: jest.fn(() => jest.fn()),
      invoke: jest.fn(),
      cancel: jest.fn(),
      hitlRespond: jest.fn(),
      feedback: jest.fn(),
      snapshot: jest.fn(),
      attachFile: jest.fn(),
      listProviders: jest.fn(),
      configSet: jest.fn(),
    } satisfies Partial<AGPClient>

    render(
      <MemoryRouter>
        <ThemeProvider>
          <AGPClientContext.Provider value={mockClient as AGPClient}>
            <SettingsPage />
          </AGPClientContext.Provider>
        </ThemeProvider>
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: /^settings$/i })).toBeInTheDocument()
    expect(screen.getAllByText(/VITE_AGP_WS_URL/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByRole('link', { name: /back to workspace/i })).toHaveAttribute('href', '/')
  })
})
