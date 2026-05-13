/** WorkerTree — hierarchical view of all spawned workers + tool calls in the active turn. */
import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Users, Wrench, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { useSessionStore } from '../../store/session.js'
import { cn, fmtDuration } from '../../lib/utils/cn.js'

export const WorkerTree = (): React.ReactElement => {
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const lastTurn = useSessionStore((s) => s.completedTurns.at(-1))
  const workers = activeTurn?.workers ?? lastTurn?.workers ?? []
  const toolCalls = activeTurn?.toolCalls ?? lastTurn?.toolCalls ?? []

  if (workers.length === 0 && toolCalls.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-neutral-600 text-sm p-6 text-center">
        Workers and tool calls appear here during execution.
      </div>
    )
  }

  return (
    <div className="p-3 flex flex-col gap-2">
      {/* Workers */}
      <AnimatePresence>
        {workers.map((w) => (
          <motion.div
            key={w.id}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            className={cn(
              'rounded-lg border p-3 flex flex-col gap-2',
              w.status === 'running' ? 'border-yellow-800/60 bg-yellow-950/20'
              : w.status === 'done'  ? 'border-emerald-800/50 bg-emerald-950/20'
              : 'border-red-800/50 bg-red-950/20',
            )}
          >
            <div className="flex items-center gap-2">
              {w.status === 'running' ? <Loader2 size={12} className="text-yellow-400 animate-spin" />
               : w.status === 'done'  ? <CheckCircle size={12} className="text-emerald-400" />
               : <XCircle size={12} className="text-red-400" />}
              <Users size={11} className="text-neutral-400" />
              <span className="text-sm font-medium text-white">{w.name}</span>
              {w.pattern && <span className="text-xs text-indigo-400 ml-auto">{w.pattern}</span>}
            </div>
            {w.task && <p className="text-xs text-neutral-500 leading-relaxed truncate">{w.task}</p>}
            {w.outputPreview && <p className="text-xs text-neutral-400 leading-relaxed line-clamp-2">{w.outputPreview}</p>}
            {w.error && <p className="text-xs text-red-400">{w.error}</p>}
          </motion.div>
        ))}
      </AnimatePresence>

      {/* Tool calls */}
      {toolCalls.map((tc) => (
        <div key={tc.id} className={cn(
          'rounded-lg border px-3 py-2 flex flex-col gap-1.5',
          tc.status === 'pending' ? 'border-yellow-800/40 bg-yellow-950/10'
          : tc.status === 'done'  ? 'border-neutral-800 bg-neutral-900/40'
          : 'border-red-800/40 bg-red-950/10',
        )}>
          <div className="flex items-center gap-2">
            {tc.status === 'pending' ? <Loader2 size={10} className="text-yellow-400 animate-spin" />
             : tc.status === 'done'  ? <CheckCircle size={10} className="text-emerald-400" />
             : <XCircle size={10} className="text-red-400" />}
            <Wrench size={10} className="text-neutral-500" />
            <span className="text-xs font-medium text-neutral-200">{tc.tool}</span>
            {tc.durationMs && <span className="text-xs text-neutral-600 ml-auto">{fmtDuration(tc.durationMs)}</span>}
          </div>
          {tc.result && <p className="text-xs text-neutral-500 line-clamp-2 font-mono">{tc.result}</p>}
          {tc.error && <p className="text-xs text-red-400">{tc.error}</p>}
        </div>
      ))}
    </div>
  )
}
