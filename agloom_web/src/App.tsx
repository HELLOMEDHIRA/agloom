/**
 * App — root React Router application.
 *
 * Routes:
 *   /                   → WorkspaceHome (session list / new session)
 *   /session/:sessionId → SessionWorkspace (main chat + runtime viz)
 *   /sessions           → SessionList
 *   /settings           → Settings (runtime URL, model, etc.)
 */

import React, { useMemo, useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { AGPClient, AGPClientContext } from './lib/agp/client.js'
import { WorkspaceHome } from './routes/WorkspaceHome.js'
import { SessionWorkspace } from './routes/SessionWorkspace.js'
import { SettingsPage } from './routes/SettingsPage.js'
import { ObservabilityDashboard } from './routes/ObservabilityDashboard.js'
import { SessionTrace } from './routes/SessionTrace.js'

// Read runtime WebSocket URL from env or default to proxied dev URL.
const RUNTIME_URL = import.meta.env['VITE_AGP_WS_URL'] ?? '/agp-ws'

export function App(): React.ReactElement {
  // One AGPClient instance per app lifetime — shared across all routes.
  const client = useMemo(() => {
    const c = new AGPClient(
      // In dev: Vite proxies /agp-ws → ws://localhost:8765
      // In prod: set VITE_AGP_WS_URL=wss://your-runtime.example.com
      RUNTIME_URL.startsWith('/')
        ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${RUNTIME_URL}`
        : RUNTIME_URL
    )
    c.connect()
    return c
  }, [])

  // Disconnect WebSocket when the component unmounts (e.g. hot-reload, StrictMode double-mount)
  // to prevent leaked connections and spurious reconnect loops.
  useEffect(() => {
    return () => {
      client.disconnect()
    }
  }, [client])

  return (
    <AGPClientContext.Provider value={client}>
      <Routes>
        <Route path="/"                            element={<WorkspaceHome />} />
        <Route path="/session/:sessionId"          element={<SessionWorkspace />} />
        <Route path="/settings"                    element={<SettingsPage />} />
        <Route path="/observe"                     element={<ObservabilityDashboard />} />
        <Route path="/observe/session/:sessionId"  element={<SessionTrace />} />
        <Route path="*"                            element={<Navigate to="/" replace />} />
      </Routes>
    </AGPClientContext.Provider>
  )
}
