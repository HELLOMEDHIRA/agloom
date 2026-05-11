import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAGPClient } from '../lib/agp/client.js'
import { useUiTheme } from '../lib/theme.js'
import { cn } from '../lib/utils/cn.js'

const MODEL_KEY = 'agloom-preferred-model-id'

export const SettingsPage = (): React.ReactElement => {
  const client = useAGPClient()
  const { theme, cycle, mode, setMode } = useUiTheme()
  const [modelId, setModelId] = useState(() => {
    try {
      return localStorage.getItem(MODEL_KEY) ?? ''
    } catch {
      return ''
    }
  })
  const [saved, setSaved] = useState(false)

  const applyModel = (): void => {
    const mid = modelId.trim()
    if (!mid) return
    try {
      localStorage.setItem(MODEL_KEY, mid)
    } catch {
      /* ignore */
    }
    client.send({
      type: 'command.config.set',
      data: { model_id: mid },
    })
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2000)
  }

  const light = theme === 'light'

  return (
    <div
      className={cn(
        'min-h-screen p-8 flex flex-col gap-6 max-w-xl mx-auto',
        light ? 'bg-neutral-50 text-neutral-900' : 'bg-neutral-950 text-white',
      )}
    >
      <div className="flex justify-between items-start gap-4">
        <h1 className="text-2xl font-bold">Settings</h1>
        <div className="flex flex-col items-end gap-2">
          <div className="flex gap-1">
            {(['dark', 'light', 'system'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={cn(
                  'text-xs px-2 py-1 rounded-md border',
                  mode === m
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200'
                    : light
                      ? 'border-neutral-200 bg-white hover:bg-neutral-50'
                      : 'border-neutral-700 bg-neutral-900 hover:bg-neutral-800',
                )}
              >
                {m === 'system' ? 'System' : m === 'dark' ? 'Dark' : 'Light'}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={cycle}
            className={cn(
              'text-xs px-3 py-1.5 rounded-lg border',
              light
                ? 'border-neutral-300 bg-white hover:bg-neutral-100'
                : 'border-neutral-700 bg-neutral-900 hover:bg-neutral-800',
            )}
          >
            Cycle theme
          </button>
        </div>
      </div>

      <section className={cn('flex flex-col gap-3 border rounded-lg p-4', light ? 'border-neutral-200 bg-white' : 'border-neutral-800 bg-neutral-900/50')}>
        <h2 className="text-sm font-semibold text-neutral-400">Model</h2>
        <p className="text-sm text-neutral-500">
          Sent to the runtime as <code className="text-neutral-300">command.config.set</code> when you apply.
          Use the same model id format as the Python runtime (e.g. <code className="text-neutral-300">openai:gpt-4o</code>).
        </p>
        <input
          value={modelId}
          onChange={(e) => setModelId(e.target.value)}
          placeholder="provider:model"
          className={cn(
            'w-full rounded-lg border px-3 py-2 text-sm font-mono',
            light ? 'bg-neutral-50 border-neutral-300 text-neutral-900' : 'bg-neutral-950 border-neutral-700 text-white',
          )}
        />
        <button
          type="button"
          onClick={applyModel}
          disabled={!modelId.trim()}
          className={cn(
            'self-start text-sm px-4 py-2 rounded-lg font-medium transition-colors',
            modelId.trim()
              ? 'bg-indigo-600 text-white hover:bg-indigo-500'
              : 'bg-neutral-700 text-neutral-500 cursor-not-allowed',
          )}
        >
          Apply to runtime
        </button>
        {saved && <p className="text-xs text-emerald-500">Preference saved and config sent.</p>}
      </section>

      <section className={cn('flex flex-col gap-2 border rounded-lg p-4 text-sm', light ? 'border-neutral-200 bg-white' : 'border-neutral-800 bg-neutral-900/50')}>
        <h2 className="text-sm font-semibold text-neutral-400">WebSocket URL</h2>
        <p className="text-neutral-500">
          Read at build time from{' '}
          <code className={light ? 'text-neutral-800' : 'text-neutral-300'}>VITE_AGP_WS_URL</code>
          . In dev, Vite proxies <code className={light ? 'text-neutral-800' : 'text-neutral-300'}>/agp-ws</code> when unset.
        </p>
      </section>

      <Link to="/" className="text-sm text-indigo-400 hover:text-indigo-300">
        ← Back to workspace
      </Link>
    </div>
  )
}
