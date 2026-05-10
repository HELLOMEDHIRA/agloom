/**
 * ObservabilityDashboard — /observe
 * Global overview: session list, summary stats, live event feed.
 */
import React from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { obsApi, type SessionSummary, type GlobalSummary } from '../lib/agp/obsApi.js'
import { cn, fmtTokens, fmtDuration } from '../lib/utils/cn.js'
import { Activity, Database, Users, Zap, Clock, AlertTriangle, CheckCircle } from 'lucide-react'
import { LiveFeed } from '../components/observability/LiveFeed.js'

export const ObservabilityDashboard = (): React.ReactElement => {
  const { data: summary } = useQuery<GlobalSummary>({
    queryKey: ['obs', 'summary'],
    queryFn: obsApi.summary,
    refetchInterval: 5000,
  })

  const { data: sessions = [] } = useQuery<SessionSummary[]>({
    queryKey: ['obs', 'sessions'],
    queryFn: () => obsApi.sessions(100),
    refetchInterval: 5000,
  })

  return (
    <div className="min-h-screen bg-neutral-950 text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-neutral-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/" className="text-indigo-400 font-bold text-sm hover:text-indigo-300">agloom</Link>
          <span className="text-neutral-700">·</span>
          <span className="text-sm font-semibold">Observability</span>
        </div>
        <Link to="/" className="text-xs text-neutral-500 hover:text-neutral-300">← Workspace</Link>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Main content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* Stats cards */}
          {summary && (
            <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3">
              {[
                { icon: <Database size={14} />, label: 'Sessions',    value: summary.total_sessions },
                { icon: <Activity size={14} />,  label: 'Active',      value: summary.open_sessions },
                { icon: <Users size={14} />,     label: 'Turns',       value: summary.total_turns },
                { icon: <Zap size={14} />,       label: 'Tokens in',   value: fmtTokens(summary.total_input_tokens) },
                { icon: <Zap size={14} />,       label: 'Tokens out',  value: fmtTokens(summary.total_output_tokens) },
                { icon: <Clock size={14} />,     label: 'Avg duration',value: fmtDuration(summary.avg_session_duration_ms) },
              ].map(({ icon, label, value }) => (
                <div key={label} className="bg-neutral-900 border border-neutral-800 rounded-xl p-4 flex flex-col gap-1">
                  <div className="flex items-center gap-1.5 text-neutral-500">{icon}<span className="text-xs">{label}</span></div>
                  <span className="text-xl font-bold text-white">{value}</span>
                </div>
              ))}
            </div>
          )}

          {/* Session list */}
          <div>
            <h2 className="text-sm font-semibold text-neutral-400 mb-3">Sessions</h2>
            <div className="flex flex-col gap-2">
              {sessions.map((s) => (
                <Link
                  key={s.session_id}
                  to={`/observe/session/${s.session_id}`}
                  className="flex items-center gap-4 px-4 py-3 bg-neutral-900 border border-neutral-800 rounded-xl hover:border-neutral-700 transition-colors"
                >
                  {/* Status dot */}
                  <span className={cn('w-2 h-2 rounded-full shrink-0',
                    s.status === 'open'   ? 'bg-emerald-400 animate-pulse'
                    : s.status === 'error'? 'bg-red-400'
                    : 'bg-neutral-600'
                  )} />

                  {/* Session ID */}
                  <span className="font-mono text-xs text-neutral-400 w-28 truncate shrink-0">{s.session_id}</span>

                  {/* Pattern */}
                  {s.pattern && <span className="text-xs text-indigo-400 shrink-0">{s.pattern}</span>}

                  {/* Stats */}
                  <div className="flex items-center gap-4 ml-auto text-xs text-neutral-500">
                    <span>{s.total_turns} turns</span>
                    <span>{fmtTokens(s.input_tokens + s.output_tokens)} tok</span>
                    {s.duration_ms && <span>{fmtDuration(s.duration_ms)}</span>}
                    <span className="text-neutral-700">{new Date(s.started_at).toLocaleString()}</span>
                    {s.status === 'error' && <AlertTriangle size={11} className="text-red-400" />}
                    {s.status === 'closed' && <CheckCircle size={11} className="text-emerald-600" />}
                  </div>
                </Link>
              ))}
              {sessions.length === 0 && (
                <p className="text-sm text-neutral-600 text-center py-8">No sessions yet. Start a session in the workspace.</p>
              )}
            </div>
          </div>
        </div>

        {/* Live feed sidebar */}
        <aside className="w-80 border-l border-neutral-800 flex flex-col">
          <div className="px-4 py-2.5 border-b border-neutral-800 shrink-0">
            <span className="text-xs font-semibold text-neutral-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
              Live events
            </span>
          </div>
          <LiveFeed />
        </aside>
      </div>
    </div>
  )
}
