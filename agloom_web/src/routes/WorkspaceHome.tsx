/** WorkspaceHome — landing page: recent sessions + new session + manage store-backed ids. */
import React, { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PlusCircle, Zap, Activity, GitBranch, Pencil, Trash2 } from 'lucide-react'
import { cn } from '../lib/utils/cn.js'
import { useAGPClient } from '../lib/agp/client.js'
import type { AGPEvent } from '../lib/agp/types.js'
import { useUiTheme } from '../lib/theme.js'
import { useSessionStore } from '../store/session.js'

export const WorkspaceHome = (): React.ReactElement => {
  const navigate = useNavigate()
  const client = useAGPClient()
  const dispatch = useSessionStore((s) => s.dispatch)
  const sessionCatalogIds = useSessionStore((s) => s.sessionCatalogIds)
  const { theme, cycle, mode } = useUiTheme()
  const [listed, setListed] = useState(false)
  const [renameFrom, setRenameFrom] = useState<string | null>(null)
  const [renameTo, setRenameTo] = useState('')

  useEffect(() => {
    const requestList = (): void => {
      client.send({ type: 'command.session.list', data: {} })
    }

    const offStatus = client.onStatus((s) => {
      if (s === 'open') requestList()
    })
    const offEv = client.onEvent((evt: AGPEvent) => {
      if (evt.type === 'runtime.sessions') {
        dispatch(evt)
        setListed(true)
      }
    })

    if (client.status === 'open') requestList()

    return () => {
      offStatus()
      offEv()
    }
  }, [client, dispatch])

  const startSession = (): void => {
    const id = `s_${Date.now().toString(36)}`
    navigate(`/session/${id}`)
  }

  const shell =
    theme === 'light'
      ? 'relative min-h-screen bg-neutral-50 text-neutral-900 flex flex-col items-center justify-center gap-10 px-4'
      : 'relative min-h-screen bg-neutral-950 flex flex-col items-center justify-center gap-10 px-4'

  const deleteSession = (id: string): void => {
    if (!window.confirm(`Delete session replay buffer "${id}"? This cannot be undone.`)) return
    client.send({ type: 'command.session.delete', data: { session_id: id } })
  }

  const submitRename = (): void => {
    if (!renameFrom) return
    const to = renameTo.trim()
    if (!to || to === renameFrom) return
    client.send({
      type: 'command.session.rename',
      data: { from_session_id: renameFrom, to_session_id: to },
    })
  }

  const themeLabel = mode === 'system' ? 'Auto' : mode === 'dark' ? 'Dark' : 'Light'

  return (
    <div className={shell}>
      <div className="absolute top-4 right-4">
        <button
          type="button"
          onClick={cycle}
          className={cn(
            'text-xs px-3 py-1.5 rounded-lg border transition-colors',
            theme === 'light'
              ? 'border-neutral-300 bg-white text-neutral-700 hover:bg-neutral-100'
              : 'border-neutral-700 bg-neutral-900 text-neutral-300 hover:bg-neutral-800',
          )}
          title="Cycle theme: dark · light · system"
        >
          Theme: {themeLabel}
        </button>
      </div>

      {/* Brand */}
      <div className="flex flex-col items-center gap-2">
        <span
          className={cn(
            'text-4xl font-bold tracking-tight',
            theme === 'light' ? 'text-neutral-900' : 'text-white',
          )}
        >
          agloom
        </span>
        <span
          className={cn('text-sm', theme === 'light' ? 'text-neutral-600' : 'text-neutral-400')}
        >
          AI-native orchestration workspace
        </span>
      </div>

      {/* New session CTA */}
      <button
        type="button"
        onClick={startSession}
        className="flex items-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-500 transition-colors rounded-xl text-white font-semibold text-sm shadow-lg shadow-indigo-900/40"
      >
        <PlusCircle size={16} />
        New session
      </button>

      {/* Feature pills */}
      <div className="flex flex-wrap justify-center gap-3 max-w-lg">
        {[
          { icon: <Zap size={13} />,       label: 'AGP streaming' },
          { icon: <Activity size={13} />,  label: 'Live execution trace' },
          { icon: <GitBranch size={13} />, label: 'LangGraph visualization' },
        ].map(({ icon, label }) => (
          <span
            key={label}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs',
              theme === 'light'
                ? 'border-neutral-200 text-neutral-600 bg-white'
                : 'border-neutral-800 text-neutral-400',
            )}
          >
            {icon} {label}
          </span>
        ))}
      </div>

      {/* Sessions from runtime */}
      {listed && sessionCatalogIds.length > 0 && (
        <div className="w-full max-w-md">
          <p
            className={cn(
              'text-xs mb-3',
              theme === 'light' ? 'text-neutral-500' : 'text-neutral-500',
            )}
          >
            Sessions on runtime (EventStore)
          </p>
          <div className="flex flex-col gap-2">
            {sessionCatalogIds.map((id) => (
              <div
                key={id}
                className={cn(
                  'flex items-stretch gap-2 rounded-xl border transition-colors',
                  theme === 'light'
                    ? 'bg-white border-neutral-200 hover:border-neutral-300'
                    : 'bg-neutral-900 border-neutral-800 hover:border-neutral-700',
                )}
              >
                <button
                  type="button"
                  onClick={() => navigate(`/session/${id}`)}
                  className={cn(
                    'flex-1 text-left px-4 py-3 min-w-0',
                    theme === 'light' ? 'text-neutral-900' : 'text-white',
                  )}
                >
                  <span className="text-sm font-mono truncate block">{id}</span>
                </button>
                <div className="flex items-center gap-0.5 pr-2 py-2">
                  <button
                    type="button"
                    title="Rename"
                    onClick={() => {
                      setRenameFrom(id)
                      setRenameTo(id)
                    }}
                    className={cn(
                      'p-2 rounded-lg transition-colors',
                      theme === 'light'
                        ? 'text-neutral-500 hover:bg-neutral-100'
                        : 'text-neutral-500 hover:bg-neutral-800',
                    )}
                  >
                    <Pencil size={14} />
                  </button>
                  <button
                    type="button"
                    title="Delete"
                    onClick={() => deleteSession(id)}
                    className="p-2 rounded-lg text-red-400/90 hover:bg-red-950/40 transition-colors"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {listed && sessionCatalogIds.length === 0 && (
        <p className={theme === 'light' ? 'text-neutral-600 text-xs' : 'text-neutral-600 text-xs'}>
          No sessions reported yet — start one above.
        </p>
      )}

      {renameFrom && (
        <div
          className={cn(
            'fixed inset-0 z-50 flex items-center justify-center p-4',
            theme === 'light' ? 'bg-black/30' : 'bg-black/50',
          )}
          role="dialog"
          aria-modal
          aria-labelledby="rename-session-title"
        >
          <div
            className={cn(
              'w-full max-w-sm rounded-xl border p-4 shadow-xl flex flex-col gap-3',
              theme === 'light'
                ? 'bg-white border-neutral-200 text-neutral-900'
                : 'bg-neutral-900 border-neutral-700 text-white',
            )}
          >
            <p id="rename-session-title" className="text-sm font-medium">Rename session</p>
            <p className="text-xs text-neutral-500 font-mono break-all">{renameFrom}</p>
            <input
              value={renameTo}
              onChange={(e) => setRenameTo(e.target.value)}
              className={cn(
                'w-full rounded-lg border px-3 py-2 text-sm font-mono',
                theme === 'light'
                  ? 'bg-neutral-50 border-neutral-300 text-neutral-900'
                  : 'bg-neutral-950 border-neutral-700 text-white',
              )}
              placeholder="new_session_id"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setRenameFrom(null)
                  setRenameTo('')
                }}
                className="text-xs px-3 py-1.5 rounded-lg text-neutral-500 hover:bg-neutral-800/50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitRename}
                className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
