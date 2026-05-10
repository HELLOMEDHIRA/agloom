/**
 * WorkspaceHome — landing page: recent sessions + new session button.
 */
import React from 'react'
import { useNavigate } from 'react-router-dom'
import { PlusCircle, Zap, Activity, GitBranch } from 'lucide-react'
import { cn } from '../lib/utils/cn.js'

const RECENT: { id: string; title: string; ts: string; pattern: string }[] = []

export function WorkspaceHome(): React.ReactElement {
  const navigate = useNavigate()

  const startSession = () => {
    const id = `s_${Date.now().toString(36)}`
    navigate(`/session/${id}`)
  }

  return (
    <div className="min-h-screen bg-neutral-950 flex flex-col items-center justify-center gap-10 px-4">

      {/* Brand */}
      <div className="flex flex-col items-center gap-2">
        <span className="text-4xl font-bold tracking-tight text-white">agloom</span>
        <span className="text-neutral-400 text-sm">AI-native orchestration workspace</span>
      </div>

      {/* New session CTA */}
      <button
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
          <span key={label} className={cn('flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-neutral-800 text-neutral-400 text-xs')}>
            {icon} {label}
          </span>
        ))}
      </div>

      {/* Recent sessions */}
      {RECENT.length > 0 && (
        <div className="w-full max-w-md">
          <p className="text-neutral-500 text-xs mb-3">Recent sessions</p>
          <div className="flex flex-col gap-2">
            {RECENT.map((s) => (
              <button
                key={s.id}
                onClick={() => navigate(`/session/${s.id}`)}
                className="flex items-center justify-between px-4 py-3 rounded-xl bg-neutral-900 border border-neutral-800 hover:border-neutral-700 transition-colors text-left"
              >
                <span className="text-sm text-white truncate">{s.title}</span>
                <span className="text-xs text-neutral-500 shrink-0 ml-3">{s.ts}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
