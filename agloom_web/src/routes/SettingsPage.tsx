import React from 'react'
import { Link } from 'react-router-dom'

export const SettingsPage = (): React.ReactElement => {
  return (
    <div className="min-h-screen bg-neutral-950 text-white p-8 flex flex-col gap-6 max-w-xl mx-auto">
      <h1 className="text-2xl font-bold">Environment</h1>
      <p className="text-sm text-neutral-400">
        The AGP WebSocket URL is read at <strong className="text-neutral-200">build time</strong> from{' '}
        <code className="text-neutral-300">VITE_AGP_WS_URL</code> (see <code className="text-neutral-300">App.tsx</code>). Add it to{' '}
        <code className="text-neutral-300">.env.local</code> and run <code className="text-neutral-300">npm run dev</code> or{' '}
        <code className="text-neutral-300">npm run build</code>. In dev, the Vite proxy maps{' '}
        <code className="text-neutral-300">/agp-ws</code> → your local runtime when the variable is unset.
      </p>

      <dl className="flex flex-col gap-3 text-sm border border-neutral-800 rounded-lg p-4 bg-neutral-900/50">
        <dt className="text-neutral-500">How to verify</dt>
        <dd className="text-neutral-300">
          Inspect <code className="text-neutral-200">import.meta.env.VITE_AGP_WS_URL</code> in the browser console on any workspace route, or open{' '}
          <code className="text-neutral-200">dist/assets/*.js</code> after a production build.
        </dd>
      </dl>

      <Link to="/" className="text-sm text-indigo-400 hover:text-indigo-300">← Back to workspace</Link>
    </div>
  )
}
