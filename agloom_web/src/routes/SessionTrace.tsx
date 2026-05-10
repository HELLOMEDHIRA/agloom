/**
 * SessionTrace — /observe/session/:sessionId
 * Full session trace: timeline, graph replay, metrics, worker traces.
 */
import React, { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { obsApi, type SessionSummary, type SessionMetrics } from '../lib/agp/obsApi.js'
import { fmtTokens, fmtDuration, cn } from '../lib/utils/cn.js'
import { TraceTimeline } from '../components/observability/TraceTimeline.js'
import { MetricsPanel } from '../components/observability/MetricsPanel.js'
import { ReplayPlayer } from '../components/observability/ReplayPlayer.js'
import { WorkerMonitor } from '../components/observability/WorkerMonitor.js'
import { ArrowLeft } from 'lucide-react'

type Tab = 'timeline' | 'metrics' | 'workers' | 'replay'

const TABS: { id: Tab; label: string }[] = [
  { id: 'timeline', label: 'Trace Timeline' },
  { id: 'metrics',  label: 'Metrics' },
  { id: 'workers',  label: 'Workers' },
  { id: 'replay',   label: 'Replay' },
]

export function SessionTrace(): React.ReactElement {
  const { sessionId } = useParams<{ sessionId: string }>()
  const [tab, setTab] = useState<Tab>('timeline')

  const { data: session } = useQuery<SessionSummary>({
    queryKey: ['obs', 'session', sessionId],
    queryFn: () => obsApi.session(sessionId!),
    enabled: !!sessionId,
    refetchInterval: (query) =>
      (query.state.data as SessionSummary | undefined)?.status === 'open' ? 3000 : false,
  })

  const { data: metrics } = useQuery<SessionMetrics>({
    queryKey: ['obs', 'metrics', sessionId],
    queryFn: () => obsApi.metrics(sessionId!),
    enabled: !!sessionId,
    refetchInterval: session?.status === 'open' ? 5000 : false,
  })

  return (
    <div className="min-h-screen bg-neutral-950 text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-neutral-800 px-6 py-3 flex items-center gap-4">
        <Link to="/observe" className="text-neutral-500 hover:text-neutral-300 transition-colors">
          <ArrowLeft size={16} />
        </Link>
        <div className="flex flex-col">
          <span className="font-mono text-xs text-neutral-400">{sessionId}</span>
          {session?.pattern && <span className="text-xs text-indigo-400">{session.pattern}</span>}
        </div>
        {session && (
          <div className="flex items-center gap-4 ml-auto text-xs text-neutral-500">
            <span>{session.total_turns} turns</span>
            <span>{fmtTokens(session.input_tokens + session.output_tokens)} tokens</span>
            {session.duration_ms && <span>{fmtDuration(session.duration_ms)}</span>}
            <span className={cn('px-2 py-0.5 rounded-full border text-xs',
              session.status === 'open'   ? 'border-emerald-700 text-emerald-400'
              : session.status === 'error'? 'border-red-700 text-red-400'
              : 'border-neutral-700 text-neutral-400'
            )}>{session.status}</span>
          </div>
        )}
      </header>

      {/* Tab bar */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-neutral-800 bg-neutral-950 shrink-0">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn('px-3 py-1.5 rounded-lg text-xs transition-colors',
              tab === t.id ? 'bg-neutral-800 text-white' : 'text-neutral-500 hover:text-neutral-300'
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {tab === 'timeline' && <TraceTimeline sessionId={sessionId!} metrics={metrics} />}
        {tab === 'metrics'  && <MetricsPanel metrics={metrics} />}
        {tab === 'workers'  && <WorkerMonitor sessionId={sessionId!} />}
        {tab === 'replay'   && <ReplayPlayer sessionId={sessionId!} />}
      </div>
    </div>
  )
}
