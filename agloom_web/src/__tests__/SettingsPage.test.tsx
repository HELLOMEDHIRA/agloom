/**
 * Smoke test for a route-level component (no AGP store dependency).
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { SettingsPage } from '../routes/SettingsPage'

describe('SettingsPage', () => {
  it('renders environment heading and build-time URL reference', () => {
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: /environment/i })).toBeInTheDocument()
    expect(screen.getAllByText(/VITE_AGP_WS_URL/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/How to verify/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /back to workspace/i })).toHaveAttribute('href', '/')
  })
})
