/** WorkerMonitor — worker + tool-call traces with status, duration, output preview. */
import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { obsApi, type EventRow } from '../../lib/agp/obsApi.js'
import { cn, fmtDuration } from '../../lib/utils/cn.js'
import { Users, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { format } from 'date-fns'

interface Props { sessionId: string }

interface WorkerRow {
  worker_id:       string
  name:            string
  pattern?:        string
  task?:           string
  spawnedAt:       string
  status:          'running' | 'done' | 'failed'
  outputPreview?:  string
  error?:          string
  duration_ms?:    number
}

const buildWorkers = (events: EventRow[]): WorkerRow[] => {
  const map = new Map<string, WorkerRow>()
  for (const ev of events) {
    const d = ev.data as Record<string, string>
    if (ev.type === 'worker.spawned') {
      map.set(d['worker_id']!, {
        worker_id: d['worker_id']!,
        name: d['name'] ?? d['worker_id']!,
        pattern: d['pattern'],
        task: d['task'],
        spawnedAt: ev.ts,
        status: 'running',
      })
    } else if (ev.type === 'worker.completed') {
      const w = map.get(d['worker_id']!)
      if (w) {
        w.status = 'done'
        w.outputPreview = d['output_preview']
        w.duration_ms = Number(d['duration_ms']) || undefined
      }
    } else if (ev.type === 'worker.failed') {
      const w = map.get(d['worker_id']!)
      if (w) {
        w.status = 'failed'
        w.error = d['error']
        w.duration_ms = Number(d['duration_ms']) || undefined
      }
    }
  }
  return [...map.values()]
}

export const WorkerMonitor = ({ sessionId }: Props): React.ReactElement => {
  const { data: events = [], isLoading } = useQuery<EventRow[]>({
    queryKey: ['obs', 'workers', sessionId],
    queryFn: () => obsApi.workers(sessionId),
    refetchInterval: 5000,
  })

  const workers = buildWorkers(events)

  if (isLoading) return <div className="flex items-center justify-center h-48 text-neutral-500 text-sm">Loading…</div>

  if (workers.length === 0) return (
    <div className="flex items-center justify-center h-48 text-neutral-600 text-sm p-6 text-center">
      No workers spawned in this session.
    </div>
  )

  return (
    <div className="h-full overflow-y-auto p-4 space-y-3">
      {workers.map((w) => (
        <div key={w.worker_id} className={cn(
          'rounded-xl border p-4 flex flex-col gap-2',
          w.status === 'running' ? 'border-yellow-800/50 bg-yellow-950/20'
          : w.status === 'done'  ? 'border-emerald-800/40 bg-emerald-950/20'
          : 'border-red-800/40 bg-red-950/20',
        )}>
          <div className="flex items-center gap-2">
            {w.status === 'running' ? <Loader2 size={13} className="text-yellow-400 animate-spin" />
             : w.status === 'done'  ? <CheckCircle size={13} className="text-emerald-400" />
             : <XCircle size={13} className="text-red-400" />}
            <Users size={12} className="text-neutral-500" />
            <span className="text-sm font-semibold text-white">{w.name}</span>
            {w.pattern && <span className="text-xs text-indigo-400">[{w.pattern}]</span>}
            <span className="text-xs text-neutral-600 ml-auto font-mono">{w.worker_id}</span>
          </div>

          {w.task && <p className="text-xs text-neutral-500 font-mono leading-relaxed">{w.task}</p>}
          {w.outputPreview && <p className="text-xs text-neutral-300 leading-relaxed line-clamp-3">{w.outputPreview}</p>}
          {w.error && <p className="text-xs text-red-400 leading-relaxed">{w.error}</p>}

          <div className="flex items-center gap-4 mt-1 text-xs text-neutral-600">
            <span>{format(new Date(w.spawnedAt), 'HH:mm:ss.SSS')}</span>
            {w.duration_ms && <span>{fmtDuration(w.duration_ms)}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}
