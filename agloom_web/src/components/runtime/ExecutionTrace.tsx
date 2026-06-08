/** ExecutionTrace — ordered log of all AGP events for the current session.
 * Provides full runtime observability: every event, its seq, timestamp, summary.
 */
import React, { useRef, useEffect } from 'react'
import { useSessionStore } from '../../store/session.js'
import { cn } from '../../lib/utils/cn.js'
import { format } from 'date-fns'

const EVENT_COLOR: Record<string, string> = {
  'session.opened':     'text-emerald-400',
  'session.closed':     'text-neutral-500',
  'pattern.classified': 'text-indigo-400',
  'thinking.step':      'text-purple-400',
  'tool.call':          'text-cyan-400',
  'tool.result':        'text-cyan-300',
  'worker.spawned':     'text-yellow-400',
  'worker.completed':   'text-emerald-300',
  'worker.failed':      'text-red-400',
  'worker.halted':      'text-cyan-400',
  'hitl.request':       'text-orange-400',
  'message.assistant':  'text-white',
  'metric.tokens':      'text-neutral-500',
  'graph.node.enter':   'text-violet-400',
  'orchestration.step': 'text-fuchsia-400',
  'graph.node.exit':    'text-violet-300',
  'checkpoint.saved':   'text-teal-400',
  'error.fatal':        'text-red-500',
  'error.transient':    'text-red-400',
}

export const ExecutionTrace = (): React.ReactElement => {
  const trace = useSessionStore((s) => s.executionTrace)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView()
  }, [trace.length])

  if (trace.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-neutral-600 text-sm p-6 text-center">
        AGP events appear here when the session starts.
      </div>
    )
  }

  return (
    <div className="flex flex-col p-2 gap-0.5 font-mono text-[11px]">
      {trace.map((te) => (
        <div key={`${te.seq}_${te.type}`} className="flex items-start gap-2 px-2 py-1 rounded hover:bg-neutral-900/60 transition-colors group">
          {/* Seq number */}
          <span className="text-neutral-700 w-7 text-right shrink-0 pt-px">{te.seq}</span>

          {/* Event type */}
          <span className={cn('shrink-0 min-w-36 max-w-48 break-all', EVENT_COLOR[te.type] ?? 'text-neutral-400')}>
            {te.type}
          </span>

          {/* Summary */}
          <span className="text-neutral-400 flex-1 whitespace-pre-wrap break-words">
            {te.summary}
          </span>

          {/* Timestamp */}
          <span className="text-neutral-700 shrink-0">
            {format(new Date(te.ts), 'HH:mm:ss.SSS')}
          </span>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
