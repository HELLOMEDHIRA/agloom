/**
 * WorkspaceLayout — three-panel responsive shell.
 *
 * ┌─────────┬──────────────────────────────┬──────────────────┐
 * │ Sidebar │         Chat (center)         │  Runtime panel   │
 * │  (left) │                              │  (right, tabs)   │
 * └─────────┴──────────────────────────────┴──────────────────┘
 */
import React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { LayoutGrid, Settings, Activity, GitBranch, Terminal, Package, BarChart2 } from 'lucide-react'
import { cn } from '../../lib/utils/cn.js'
import { useSessionStore } from '../../store/session.js'
import type { RightTab } from '../../routes/SessionWorkspace.js'

interface Props {
  leftSlot: React.ReactNode
  centerSlot: React.ReactNode
  rightSlot: React.ReactNode
  rightTab: RightTab
  onRightTabChange: (t: RightTab) => void
}

const RIGHT_TABS: { id: RightTab; label: string; icon: React.ReactNode }[] = [
  { id: 'graph',     label: 'Graph',   icon: <GitBranch size={13} /> },
  { id: 'workers',   label: 'Workers', icon: <Activity size={13} /> },
  { id: 'trace',     label: 'Trace',   icon: <Terminal size={13} /> },
  { id: 'artifacts', label: 'Files',   icon: <Package size={13} /> },
]

export function WorkspaceLayout({ leftSlot, centerSlot, rightSlot, rightTab, onRightTabChange }: Props): React.ReactElement {
  const navigate = useNavigate()
  const connStatus = useSessionStore((s) => s.connectionStatus)
  const status = useSessionStore((s) => s.status)

  const statusDot = {
    open:       'bg-emerald-400',
    connecting: 'bg-yellow-400 animate-pulse',
    error:      'bg-red-400',
    closed:     'bg-neutral-500',
  }[connStatus] ?? 'bg-neutral-500'

  return (
    <div className="h-screen flex flex-col bg-neutral-950 text-neutral-100 overflow-hidden">

      {/* ── Top bar ── */}
      <header className="flex items-center justify-between h-11 px-4 border-b border-neutral-800 shrink-0">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/')} className="text-indigo-400 font-bold text-sm tracking-tight hover:text-indigo-300">
            agloom
          </button>
          <span className="text-neutral-700">·</span>
          <span className={cn('w-2 h-2 rounded-full', statusDot)} title={connStatus} />
          <span className="text-xs text-neutral-500">{connStatus}</span>
        </div>

        <div className="flex items-center gap-1">
          {status !== 'idle' && (
            <span className="text-xs text-neutral-400 px-2 py-0.5 rounded-full border border-neutral-700 mr-2">
              {status}
            </span>
          )}
          <Link to="/observe" className="p-1.5 text-neutral-500 hover:text-neutral-300 transition-colors" title="Observability">
            <BarChart2 size={15} />
          </Link>
          <Link to="/settings" className="p-1.5 text-neutral-500 hover:text-neutral-300 transition-colors">
            <Settings size={15} />
          </Link>
          <Link to="/" className="p-1.5 text-neutral-500 hover:text-neutral-300 transition-colors">
            <LayoutGrid size={15} />
          </Link>
        </div>
      </header>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left sidebar — session history */}
        <aside className="w-52 shrink-0 border-r border-neutral-800 flex flex-col overflow-hidden hidden lg:flex">
          {leftSlot}
        </aside>

        {/* Center — chat */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {centerSlot}
        </main>

        {/* Right panel */}
        <aside className="w-[380px] shrink-0 border-l border-neutral-800 flex flex-col overflow-hidden">
          {/* Tab bar */}
          <div className="flex items-center gap-0.5 px-2 py-1.5 border-b border-neutral-800 shrink-0">
            {RIGHT_TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => onRightTabChange(t.id)}
                className={cn(
                  'flex items-center gap-1 px-2.5 py-1 rounded-md text-xs transition-colors',
                  rightTab === t.id
                    ? 'bg-neutral-800 text-white'
                    : 'text-neutral-500 hover:text-neutral-300'
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
