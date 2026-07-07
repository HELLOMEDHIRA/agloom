/** App — root React Router application.
 * Routes: / → WorkspaceHome (session list / new session) /session/:sessionId → SessionWorkspace (main chat + runtime viz) /sessions → SessionList /settings → Settings (runtime URL, model, etc.)
 */

import React, { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { createAGPClient, AGPClientContext } from './lib/agp/client.js'
import { useSessionStore } from './store/session.js'
import { WorkspaceHome } from './routes/WorkspaceHome.js'
import { SessionWorkspace } from './routes/SessionWorkspace.js'
import { SettingsPage } from './routes/SettingsPage.js'
import { ObservabilityDashboard } from './routes/ObservabilityDashboard.js'
import { SessionTrace } from './routes/SessionTrace.js'

// Read runtime WebSocket URL from env or default to proxied dev URL.
const RUNTIME_URL = import.meta.env['VITE_AGP_WS_URL'] ?? '/agp-ws'

export const App = (): React.ReactElement => {
  const [client] = useState(() => {
    const url =
      RUNTIME_URL.startsWith('/')
        ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}${RUNTIME_URL}`
        : RUNTIME_URL
    return createAGPClient(url, 2000, {
      getResumeState: () => {
        const s = useSessionStore.getState()
        return { thread: s.activeThreadId, fromSeq: s.lastSeenSeq ?? 0 }
      },
    })
  })

  useEffect(() => {
    client.connect()
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
