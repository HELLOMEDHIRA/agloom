/**
 * LiveFeed — SSE-based realtime event ticker for the /observe dashboard sidebar.
 * Shows last N events across all sessions in the system.
 */
import React, { useEffect, useRef, useState } from 'react'
import { obsApi } from '../../lib/agp/obsApi.js'
import type { AGPEvent } from '../../lib/agp/types.js'
import { cn } from '../../lib/utils/cn.js'
import { format } from 'date-fns'

const TYPE_COLOR: Record<string, string> = {
  'session.opened':     'text-emerald-400',
  'session.closed':     'text-neutral-500',
  'error.fatal':        'text-red-400',
  'error.transient':    'text-orange-400',
  'worker.failed':      'text-red-400',
  'worker.spawned':     'text-yellow-400',
  'message.assistant':  'text-white',
  'hitl.request':       'text-orange-400',
}

interface LiveEvent {
  id:      number
  type:    string
  session: string
  ts:      string
  summary: string
}

let _counter = 0
function summarise(evt: AGPEvent): string {
  const d = (evt as unknown as Record<string, unknown>)['data'] as Record<string, unknown> ?? {}
  switch (evt.type) {
    case 'session.opened':    return `session opened`
    case 'session.closed':    return `${d['reason'] ?? '?'}`
    case 'message.user':      return `user: ${String(d['content'] ?? '').slice(0, 40)}`
    case 'message.assistant': return `response`
    case 'tool.call.start':   return `tool: ${d['tool'] ?? '?'}()`
    case 'worker.spawned':    return `worker: ${d['name'] ?? '?'}`
    case 'hitl.request':      return `HITL: ${d['kind'] ?? '?'}`
    case 'error.fatal':       return `fatal: ${String(d['message'] ?? '').slice(0, 40)}`
    default:                  return evt.type
  }
}

export function LiveFeed(): React.ReactElement {
  const [events, setEvents] = useState<LiveEvent[]>([])
  const [connected, setConnected] = useState(false)
  const esRef = useRef<EventSource | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const url = obsApi.liveUrl()
    const es = new EventSource(url)
    esRef.current = es

    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)

    es.onmessage = (e) => {
      if (!e.data || (e.data as string).trim() === '') return
      try {
        const envelope = JSON.parse(e.data as string) as AGPEvent
        // Skip token deltas — too noisy
        if (envelope.type === 'token.delta') return
        setEvents((prev) => {
          const next = [...prev, {
            id: ++_counter,
            type: envelope.type,
            session: (envelope.session ?? '').slice(0, 10),
            ts: envelope.ts,
            summary: summarise(envelope),
          }]
          return next.slice(-200)  // keep last 200
        })
      } catch { /* non-JSON heartbeat */ }
    }

    return () => { es.close(); esRef.current = null; setConnected(false) }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView()
  }, [events.length])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {!connected && (
        <div className="px-3 py-2 text-xs text-neutral-600 border-b border-neutral-800">
          Connecting to live feed…
        </div>
      )}
      <div className="flex-1 overflow-y-auto font-mono text-[11px]">
        {events.map((ev) => (
          <div key={ev.id} className="flex items-start gap-2 px-3 py-1 hover:bg-neutral-900/50">
            <span className="text-neutral-700 shrink-0">{ev.session}</span>
            <span className={cn('shrink-0', TYPE_COLOR[ev.type] ?? 'text-neutral-400')}>
              {ev.type.split('.').slice(-1)[0]}
            </span>
            <span className="text-neutral-500 flex-1 truncate">{ev.summary}</span>
            <span className="text-neutral-700 shrink-0">{format(new Date(ev.ts), 'HH:mm:ss')}</span>
          </div>
        ))}
        {events.length === 0 && connected && (
          <div className="text-neutral-600 text-xs px-3 py-4">Waiting for events…</div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
