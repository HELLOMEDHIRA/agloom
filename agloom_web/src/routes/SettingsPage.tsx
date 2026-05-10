import React from 'react'
import { Link } from 'react-router-dom'

export function SettingsPage(): React.ReactElement {
  return (
    <div className="min-h-screen bg-neutral-950 text-white p-8 flex flex-col gap-6 max-w-xl mx-auto">
      <h1 className="text-2xl font-bold">Settings</h1>

      <section className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <label className="text-sm text-neutral-400">Runtime WebSocket URL</label>
          <input
            type="text"
            defaultValue={import.meta.env['VITE_AGP_WS_URL'] ?? 'ws://localhost:8765'}
            className="bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500"
            placeholder="ws://localhost:8765"
          />
          <span className="text-xs text-neutral-500">Connect to an agloom-runtime WebSocket endpoint.</span>
        </div>
      </section>

      <Link to="/" className="text-sm text-indigo-400 hover:text-indigo-300">← Back to workspace</Link>
    </div>
  )
}
