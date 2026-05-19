/** Live in-flight turn (re-renders on token deltas). */
import React from 'react'
import type { ActiveTurnState } from '../../store/session.js'
import { cn } from '../../lib/utils/cn.js'
import { stripStrayToolJsonFromStream } from '../../lib/utils/strayToolJson.js'
import { stripAgloomToolResultEnvelope } from '../../lib/utils/assistantText.js'
import { workerLineClass } from '../../lib/workerStatus.js'
import { Loader2, Users, Octagon } from 'lucide-react'
import { ToolCallRow } from './ToolCallRow.js'
import { ThinkingTrace } from './ThinkingTrace.js'

interface Props { turn: ActiveTurnState }

export const StreamingTurn = ({ turn }: Props): React.ReactElement => {
  const { userMessage, thinkingSteps, toolCalls, workers, streamedTokens, pattern } = turn
  const displayStream = stripStrayToolJsonFromStream(
    stripAgloomToolResultEnvelope(streamedTokens),
    new Set(),
    { permissive: true },
  )

  return (
    <article className="flex flex-col gap-4">
      <div className="flex gap-3 justify-end">
        <div className="max-w-4/5 px-4 py-2.5 rounded-2xl rounded-br-sm bg-indigo-600 text-white text-sm">
          {userMessage}
        </div>
      </div>

      {(pattern || thinkingSteps.length > 0 || workers.length > 0 || toolCalls.length > 0) && (
        <div className="flex flex-col gap-1.5 pl-3 border-l-2 border-indigo-900/60 ml-1">
          {pattern && <span className="text-xs text-indigo-400 font-medium">▸ {pattern}</span>}

          <ThinkingTrace steps={thinkingSteps} />

          {workers.map((w) => (
            <div key={w.id} className={cn('flex items-center gap-1.5 text-xs', workerLineClass(w.status))}>
              {w.status === 'halted'
                ? <Octagon size={9} className="text-cyan-400 shrink-0" />
                : <Users size={9} className="shrink-0" />}
              {w.name} {w.pattern && `[${w.pattern}]`}
              {w.status === 'running' && <Loader2 size={9} className="animate-spin" />}
              {w.status === 'halted' && w.outputPreview && (
                <span className="text-cyan-500/80 whitespace-pre-wrap">{w.outputPreview}</span>
              )}
            </div>
          ))}

          {toolCalls.map((tc) => (
            <ToolCallRow key={tc.id} tc={tc} />
          ))}
        </div>
      )}

      <div className="flex gap-3">
        <div className="w-7 h-7 rounded-full bg-linear-to-br from-indigo-500 to-purple-600 shrink-0 mt-0.5 flex items-center justify-center text-xs font-bold">A</div>
        <div className="flex-1 min-w-0">
          {displayStream ? (
            <p className="text-sm text-neutral-100 leading-relaxed whitespace-pre-wrap">{displayStream}<span className="inline-block w-0.5 h-4 bg-indigo-400 ml-0.5 animate-pulse align-text-bottom" /></p>
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
