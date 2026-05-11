/**
 * WorkspaceLayout — three-panel responsive shell.
 *
 * ┌─────────┬──────────────────────────────┬──────────────────┐
 * │ Sidebar │         Chat (center)         │  Runtime panel   │
 * │  (left) │                              │  (right, tabs)   │
 * └─────────┴──────────────────────────────┴──────────────────┘
 */
import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { LayoutGrid, Settings, Activity, GitBranch, Terminal, Package, BarChart2, Menu } from 'lucide-react'
import { cn } from '../../lib/utils/cn.js'
import { useSessionStore } from '../../store/session.js'
import type { RightTab } from '../../routes/SessionWorkspace.js'
import { useUiTheme } from '../../lib/theme.js'
import type { AGPClient } from '../../lib/agp/client.js'

interface Props {
  leftSlot: React.ReactNode
  centerSlot: React.ReactNode
  rightSlot: React.ReactNode
  rightTab: RightTab
  onRightTabChange: (t: RightTab) => void
  /** When set, mobile drawer can refresh session list and show search. */
  agpClient?: AGPClient
}

const RIGHT_TABS: { id: RightTab; label: string; icon: React.ReactNode }[] = [
  { id: 'graph',     label: 'Graph',   icon: <GitBranch size={13} /> },
  { id: 'workers',   label: 'Workers', icon: <Activity size={13} /> },
  { id: 'trace',     label: 'Trace',   icon: <Terminal size={13} /> },
  { id: 'artifacts', label: 'Files',   icon: <Package size={13} /> },
]

export const WorkspaceLayout = ({ leftSlot, centerSlot, rightSlot, rightTab, onRightTabChange, agpClient }: Props): React.ReactElement => {
  const navigate = useNavigate()
  const { theme, cycle, mode } = useUiTheme()
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const [sessionSearch, setSessionSearch] = useState('')
  const connStatus = useSessionStore((s) => s.connectionStatus)
  const status = useSessionStore((s) => s.status)
  const lastProtocolNote = useSessionStore((s) => s.protocolNotes.at(-1) ?? '')
  const sessionCatalogIds = useSessionStore((s) => s.sessionCatalogIds)

  const filteredSessions = useMemo(() => {
    const q = sessionSearch.trim().toLowerCase()
    if (!q) return sessionCatalogIds
    return sessionCatalogIds.filter((id) => id.toLowerCase().includes(q))
  }, [sessionCatalogIds, sessionSearch])

  useEffect(() => {
    if (!mobileSidebar || !agpClient) return
    agpClient.send({ type: 'command.session.list', data: {} })
  }, [mobileSidebar, agpClient])

  const statusDot = {
    open:       'bg-emerald-400',
    connecting: 'bg-yellow-400 animate-pulse',
    error:      'bg-red-400',
    closed:     'bg-neutral-500',
  }[connStatus] ?? 'bg-neutral-500'

  const shell = theme === 'light'
    ? 'bg-neutral-100 text-neutral-900'
    : 'bg-neutral-950 text-neutral-100'
  const barBorder = theme === 'light' ? 'border-neutral-200' : 'border-neutral-800'
  const muted = theme === 'light' ? 'text-neutral-500' : 'text-neutral-500'
  const asideBorder = theme === 'light' ? 'border-neutral-200' : 'border-neutral-800'

  return (
    <div className={cn('h-screen flex flex-col overflow-hidden', shell)}>

      {/* ── Top bar ── */}
      <header className={cn('flex items-center justify-between h-11 px-4 border-b shrink-0', barBorder)}>
        <div className="flex items-center gap-3">
          <button
            type="button"
            className={cn('lg:hidden p-1 rounded-md', theme === 'light' ? 'hover:bg-neutral-200' : 'hover:bg-neutral-800')}
            onClick={() => setMobileSidebar(true)}
            title="Open session sidebar"
          >
            <Menu size={18} className={muted} />
          </button>
          <button onClick={() => navigate('/')} className="text-indigo-400 font-bold text-sm tracking-tight hover:text-indigo-300">
            agloom
          </button>
          <span className="text-neutral-400 dark:text-neutral-700">·</span>
          <span className={cn('w-2 h-2 rounded-full', statusDot)} title={connStatus} />
          <span className={cn('text-xs', muted)}>{connStatus}</span>
        </div>

        <div className="flex items-center gap-1">
          {status !== 'idle' && (
            <span
              className={cn(
                'text-xs px-2 py-0.5 rounded-full border mr-2',
                theme === 'light'
                  ? 'text-neutral-600 border-neutral-300'
                  : 'text-neutral-400 border-neutral-700',
              )}
            >
              {status}
            </span>
          )}
          <button
            type="button"
            onClick={cycle}
            className={cn(
              'text-xs px-2 py-0.5 rounded-md mr-1 border',
              theme === 'light'
                ? 'border-neutral-300 text-neutral-600 hover:bg-neutral-200'
                : 'border-neutral-700 text-neutral-400 hover:bg-neutral-800',
            )}
            title="Cycle theme: dark · light · system"
          >
            {mode === 'system' ? 'Auto' : mode === 'dark' ? 'Dark' : 'Light'}
          </button>
          <Link to="/observe" className={cn('p-1.5 transition-colors', muted, 'hover:opacity-80')} title="Observability">
            <BarChart2 size={15} />
          </Link>
          <Link to="/settings" className={cn('p-1.5 transition-colors', muted, 'hover:opacity-80')}>
            <Settings size={15} />
          </Link>
          <Link to="/" className={cn('p-1.5 transition-colors', muted, 'hover:opacity-80')}>
            <LayoutGrid size={15} />
          </Link>
        </div>
      </header>

      {lastProtocolNote ? (
        <div
          className={cn(
            'shrink-0 px-4 py-1.5 text-xs truncate border-b',
            theme === 'light'
              ? 'text-amber-900 bg-amber-100 border-amber-200'
              : 'text-amber-300/90 bg-amber-950/30 border-amber-900/40',
          )}
          title={lastProtocolNote}
        >
          {lastProtocolNote}
        </div>
      ) : null}

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden relative">

        {mobileSidebar && (
          <button
            type="button"
            className="fixed inset-0 z-40 bg-black/40 lg:hidden"
            aria-label="Close sidebar"
            onClick={() => setMobileSidebar(false)}
          />
        )}

        {/* Left sidebar — session history */}
        <aside
          className={cn(
            'w-52 shrink-0 border-r flex flex-col overflow-hidden z-50 lg:z-auto',
            asideBorder,
            'fixed inset-y-0 left-0 lg:static',
            'transition-transform duration-200 ease-out lg:transition-none',
            mobileSidebar ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
            theme === 'light' ? 'bg-neutral-50' : 'bg-neutral-950',
          )}
        >
          {agpClient && (
            <div className="lg:hidden shrink-0 border-b border-neutral-200 dark:border-neutral-800 p-2 space-y-2">
              <input
                type="search"
                value={sessionSearch}
                onChange={(e) => setSessionSearch(e.target.value)}
                placeholder="Search sessions…"
                className="w-full rounded-md border border-neutral-300 bg-white px-2 py-1 text-xs dark:border-neutral-700 dark:bg-neutral-900"
                aria-label="Filter sessions by id"
              />
              <nav className="max-h-28 overflow-y-auto flex flex-col gap-0.5" aria-label="Sessions">
                {filteredSessions.length === 0 ? (
                  <span className="text-[10px] text-neutral-500 px-1">No matches</span>
                ) : (
                  filteredSessions.map((id) => (
                    <Link
                      key={id}
                      to={`/session/${id}`}
                      onClick={() => setMobileSidebar(false)}
                      className="truncate rounded px-1 py-0.5 font-mono text-[10px] text-indigo-600 hover:bg-neutral-100 dark:text-indigo-400 dark:hover:bg-neutral-900"
                    >
                      {id}
                    </Link>
                  ))
                )}
              </nav>
            </div>
          )}
          <div className="flex-1 min-h-0 overflow-hidden flex flex-col">{leftSlot}</div>
        </aside>

        {/* Center — chat */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {centerSlot}
        </main>

        {/* Right panel */}
        <aside className={cn('w-[380px] shrink-0 border-l overflow-hidden hidden lg:flex lg:flex-col', asideBorder)}>
          {/* Tab bar */}
          <div className={cn('flex items-center gap-0.5 px-2 py-1.5 border-b shrink-0', barBorder)}>
            {RIGHT_TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => onRightTabChange(t.id)}
                className={cn(
                  'flex items-center gap-1 px-2.5 py-1 rounded-md text-xs transition-colors',
                  rightTab === t.id
                    ? 'bg-neutral-200 text-neutral-900 dark:bg-neutral-800 dark:text-white'
                    : 'text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300'
                )}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-y-auto">
            {rightSlot}
          </div>
        </aside>
      </div>
    </div>
  )
}
