/** TraceTimeline — horizontal swimlane timeline of all AGP events.
 * Renders each event as a chip on a time axis, grouped by event category. Colour-coded by event type; duration shown as width (where available).
 */
import React, { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { obsApi, type EventRow, type SessionMetrics } from '../../lib/agp/obsApi.js'
import { cn } from '../../lib/utils/cn.js'
import { format } from 'date-fns'

interface Props {
  sessionId: string
  metrics?:  SessionMetrics
}

const TYPE_COLOR: Record<string, string> = {
  'session.opened':     'bg-emerald-900/80 border-emerald-700 text-emerald-300',
  'session.closed':     'bg-neutral-800 border-neutral-700 text-neutral-400',
  'pattern.classified': 'bg-indigo-900/80 border-indigo-700 text-indigo-300',
  'thinking.step':      'bg-purple-900/80 border-purple-700 text-purple-300',
  'tool.call':          'bg-cyan-900/80 border-cyan-700 text-cyan-300',
  'tool.result':        'bg-cyan-950/80 border-cyan-800 text-cyan-400',
  'worker.spawned':     'bg-yellow-900/80 border-yellow-700 text-yellow-300',
  'worker.completed':   'bg-emerald-950/80 border-emerald-800 text-emerald-400',
  'worker.failed':      'bg-red-900/80 border-red-700 text-red-300',
  'worker.halted':      'bg-cyan-900/80 border-cyan-700 text-cyan-300',
  'hitl.request':       'bg-orange-900/80 border-orange-700 text-orange-300',
  'graph.node.enter':   'bg-violet-900/80 border-violet-700 text-violet-300',
  'orchestration.step': 'bg-fuchsia-900/80 border-fuchsia-700 text-fuchsia-300',
  'graph.node.exit':    'bg-violet-950/80 border-violet-800 text-violet-400',
  'checkpoint.saved':   'bg-teal-900/80 border-teal-700 text-teal-300',
  'message.user':       'bg-indigo-800/80 border-indigo-600 text-indigo-200',
  'message.assistant':  'bg-white/5 border-white/10 text-white',
  'metric.tokens':      'bg-neutral-900 border-neutral-700 text-neutral-500',
  'error.fatal':        'bg-red-950/80 border-red-700 text-red-300',
  'error.transient':    'bg-red-950/50 border-red-800 text-red-400',
}

const SWIMLANE_ORDER = [
  'session', 'pattern', 'graph', 'worker', 'tool', 'thinking', 'message', 'hitl', 'metric', 'error',
]

const lane = (type: string): string => {
  if (type.startsWith('session'))   return 'session'
  if (type.startsWith('pattern'))   return 'pattern'
  if (type.startsWith('graph'))     return 'graph'
  if (type.startsWith('worker'))    return 'worker'
  if (type.startsWith('tool'))      return 'tool'
  if (type.startsWith('thinking'))  return 'thinking'
  if (type.startsWith('message'))   return 'message'
  if (type.startsWith('hitl'))      return 'hitl'
  if (type.startsWith('metric'))    return 'metric'
  if (type.startsWith('error'))     return 'error'
  return 'other'
}

const shortLabel = (type: string, data: Record<string, unknown>): string => {
  const d = data as Record<string, string>
  switch (type) {
    case 'tool.call':         return `${d['tool'] ?? '?'}()`
    case 'tool.result':       return `${d['tool'] ?? '?'} ${d['error'] ? '✗' : '✓'}`
    case 'worker.spawned':    return d['name'] ?? '?'
    case 'worker.completed':  return `done: ${d['worker_id'] ?? '?'}`
    case 'worker.halted':     return `halt: ${d['worker_id'] ?? '?'}`
    case 'graph.node.enter':  return `→ ${d['node'] ?? '?'}`
    case 'graph.node.exit':   return `← ${d['node'] ?? '?'}`
    case 'orchestration.step': return `↻ d${d['depth'] ?? '0'} ${d['pattern'] ?? '?'} ${d['action'] ?? ''}`
    case 'thinking.step':     return d['label'] ?? d['step'] ?? '?'
    case 'pattern.classified':return d['pattern'] ?? '?'
    case 'hitl.request':      return d['kind'] ?? '?'
    default:                  return type.split('.').pop() ?? type
  }
}

export const TraceTimeline = ({ sessionId }: Props): React.ReactElement => {
  const { data: events = [], isLoading } = useQuery<EventRow[]>({
    queryKey: ['obs', 'events', sessionId],
    queryFn: () => obsApi.events(sessionId, 1000),
    refetchInterval: 5000,
  })

  const lanes = useMemo(() => {
    const map = new Map<string, EventRow[]>()
    for (const ev of events) {
      const l = lane(ev.type)
      if (!map.has(l)) map.set(l, [])
      map.get(l)!.push(ev)
    }
    // Sort by swimlane order
    return SWIMLANE_ORDER.filter((l) => map.has(l)).map((l) => ({ lane: l, events: map.get(l)! }))
  }, [events])

  if (isLoading) return <div className="flex items-center justify-center h-48 text-neutral-500 text-sm">Loading trace…</div>
  if (events.length === 0) return <div className="flex items-center justify-center h-48 text-neutral-600 text-sm">No events recorded for this session.</div>

  return (
    <div className="h-full overflow-auto p-4">
      <div className="flex flex-col gap-3">
        {lanes.map(({ lane: l, events: laneEvents }) => (
          <div key={l} className="flex items-start gap-3">
            {/* Lane label */}
            <div className="w-20 text-right text-xs text-neutral-600 shrink-0 pt-1.5 font-medium">
              {l}
            </div>

            {/* Events */}
            <div className="flex flex-wrap gap-1.5 flex-1">
              {laneEvents.map((ev) => (
                <div
                  key={ev.seq}
                  title={`seq=${ev.seq}  ts=${ev.ts}\n${JSON.stringify(ev.data, null, 2)}`}
                  className={cn(
                    'inline-flex items-center gap-1 px-2 py-1 rounded-md border text-xs cursor-default whitespace-nowrap',
                    TYPE_COLOR[ev.type] ?? 'bg-neutral-900 border-neutral-700 text-neutral-400',
                  )}
                >
                  <span className="text-[10px] text-current/50 mr-0.5">{ev.seq}</span>
                  {shortLabel(ev.type, (ev.data ?? {}) as Record<string, unknown>)}
                  {(() => {
                    const d = (ev.data ?? {}) as Record<string, unknown>
                    const ms = d['duration_ms'] ?? d['elapsed_ms']
                    return ms ? (
                      <span className="text-[10px] opacity-60 ml-0.5">
                        {Math.round(Number(ms))}ms
                      </span>
                    ) : null
                  })()}
                </div>
              ))}
            </div>

            {/* First / last timestamp */}
            <div className="text-[10px] text-neutral-700 shrink-0 pt-1.5 font-mono">
              {format(new Date(laneEvents[0]!.ts), 'HH:mm:ss')}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
