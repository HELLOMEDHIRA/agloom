/**
 * StreamingTurn — the live in-flight turn while the agent is running.
 * Re-renders on every token delta. Kept lightweight.
 */
import React from 'react'
import type { ActiveTurnState } from '../../store/session.js'
import { cn, fmtDuration } from '../../lib/utils/cn.js'
import { Loader2, Wrench, Users, Brain } from 'lucide-react'

interface Props { turn: ActiveTurnState }

export const StreamingTurn = ({ turn }: Props): React.ReactElement => {
  const { userMessage, thinkingSteps, toolCalls, workers, streamedTokens, pattern } = turn

  return (
    <article className="flex flex-col gap-4">
      {/* User message echo */}
      <div className="flex gap-3 justify-end">
        <div className="max-w-[80%] px-4 py-2.5 rounded-2xl rounded-br-sm bg-indigo-600 text-white text-sm">
          {userMessage}
        </div>
      </div>

      {/* Live trace */}
      {(pattern || thinkingSteps.length > 0 || workers.length > 0 || toolCalls.length > 0) && (
        <div className="flex flex-col gap-1.5 pl-3 border-l-2 border-indigo-900/60 ml-1">
          {pattern && <span className="text-xs text-indigo-400 font-medium">▸ {pattern}</span>}

          {thinkingSteps.slice(-4).map((s) => (
            <div key={s.id} className="flex items-center gap-1.5 text-xs text-neutral-500">
              <Brain size={9} className="text-neutral-600" />
              {s.label ?? s.step}
              {s.elapsedMs && <span className="text-neutral-700">{fmtDuration(s.elapsedMs)}</span>}
            </div>
          ))}

          {workers.map((w) => (
            <div key={w.id} className={cn('flex items-center gap-1.5 text-xs', w.status === 'running' ? 'text-yellow-400' : w.status === 'done' ? 'text-emerald-400' : 'text-red-400')}>
              <Users size={9} />
              {w.name} {w.pattern && `[${w.pattern}]`}
              {w.status === 'running' && <Loader2 size={9} className="animate-spin" />}
            </div>
          ))}

          {toolCalls.map((tc) => (
            <div key={tc.id} className={cn('flex items-center gap-1.5 text-xs', tc.status === 'pending' ? 'text-yellow-400' : tc.status === 'done' ? 'text-neutral-400' : 'text-red-400')}>
              {tc.status === 'pending' && <Loader2 size={9} className="animate-spin" />}
              <Wrench size={9} />
              {tc.tool}
              {tc.durationMs && <span className="text-neutral-600 ml-1">{fmtDuration(tc.durationMs)}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Streaming response */}
      <div className="flex gap-3">
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 shrink-0 mt-0.5 flex items-center justify-center text-xs font-bold">A</div>
        <div className="flex-1 min-w-0">
          {streamedTokens ? (
            <p className="text-sm text-neutral-100 leading-relaxed whitespace-pre-wrap">{streamedTokens}<span className="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom" /></p>
          ) : (
            <div className="flex items-center gap-2 text-sm text-neutral-500">
              <Loader2 size={13} className="animate-spin text-indigo-400" />
              <span>thinking…</span>
            </div>
          )}
        </div>
      </div>
    </article>
  )
}
