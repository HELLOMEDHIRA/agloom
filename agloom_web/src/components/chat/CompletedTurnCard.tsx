/**
 * CompletedTurnCard — renders a finished turn (never re-renders after mount).
 */
import React, { memo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { CompletedTurn } from '../../store/session.js'
import { cn, fmtDuration } from '../../lib/utils/cn.js'
import { CheckCircle, XCircle, Clock, Wrench, Users } from 'lucide-react'

interface Props { turn: CompletedTurn }

export const CompletedTurnCard = memo(({ turn }: Props) => {
  return (
    <article className="flex flex-col gap-4">
      {/* User message */}
      <div className="flex gap-3 justify-end">
        <div className="max-w-[80%] px-4 py-2.5 rounded-2xl rounded-br-sm bg-indigo-600 text-white text-sm leading-relaxed">
          {turn.userMessage}
        </div>
      </div>

      {/* Trace summary: pattern + thinking + tools + workers */}
      {(turn.pattern || turn.thinkingSteps.length > 0 || turn.toolCalls.length > 0 || turn.workers.length > 0) && (
        <div className="flex flex-col gap-1.5 pl-3 border-l-2 border-neutral-800 ml-1">
          {turn.pattern && (
            <span className="text-xs text-indigo-400 font-medium">▸ {turn.pattern}</span>
          )}
          {turn.thinkingSteps.slice(0, 3).map((s) => (
            <span key={s.id} className="text-xs text-neutral-500">▸ {s.label ?? s.step}</span>
          ))}
          {turn.thinkingSteps.length > 3 && (
            <span className="text-xs text-neutral-600">▸ +{turn.thinkingSteps.length - 3} more steps</span>
          )}
          {turn.workers.map((w) => (
            <div key={w.id} className="flex items-center gap-1.5 text-xs">
              <Users size={10} className={w.status === 'done' ? 'text-emerald-400' : 'text-red-400'} />
              <span className="text-neutral-400">{w.name}</span>
              {w.pattern && <span className="text-neutral-600">[{w.pattern}]</span>}
            </div>
          ))}
          {turn.toolCalls.map((tc) => (
            <div key={tc.id} className="flex items-center gap-1.5 text-xs">
              {tc.status === 'done'    && <CheckCircle size={10} className="text-emerald-400" />}
              {tc.status === 'error'   && <XCircle size={10} className="text-red-400" />}
              {tc.status === 'pending' && <Clock size={10} className="text-yellow-400" />}
              <Wrench size={10} className="text-neutral-500" />
              <span className="text-neutral-400">{tc.tool}</span>
              {tc.durationMs && <span className="text-neutral-600">{fmtDuration(tc.durationMs)}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Assistant response */}
      <div className="flex gap-3">
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 shrink-0 mt-0.5 flex items-center justify-center text-xs font-bold">A</div>
        <div className="flex-1 min-w-0">
          <div className={cn(
            'prose prose-sm prose-invert max-w-none',
            'prose-pre:bg-neutral-900 prose-pre:border prose-pre:border-neutral-800 prose-pre:rounded-lg',
            'prose-code:text-indigo-300 prose-code:bg-neutral-900 prose-code:px-1 prose-code:py-0.5 prose-code:rounded',
            'prose-a:text-indigo-400',
          )}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
              {turn.assistantMessage}
            </ReactMarkdown>
          </div>

          {/* Footer: tokens + pattern */}
          <div className="flex items-center gap-3 mt-2">
            {turn.tokens && <span className="text-xs text-neutral-600">{turn.tokens} tok</span>}
            {turn.pattern && <span className="text-xs text-neutral-600">{turn.pattern}</span>}
            {turn.artifacts.length > 0 && (
              <span className="text-xs text-indigo-500">{turn.artifacts.length} artifact{turn.artifacts.length > 1 ? 's' : ''}</span>
            )}
          </div>
        </div>
      </div>
    </article>
  )
})

CompletedTurnCard.displayName = 'CompletedTurnCard'
