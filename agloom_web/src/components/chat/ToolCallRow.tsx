/** Collapsible tool row (summary + optional body / diff). */
import React from 'react'
import { CheckCircle, XCircle, Wrench, ChevronRight, ChevronDown, Loader2 } from 'lucide-react'
import type { ToolCall } from '../../store/session.js'
import { effectiveToolCallExpanded, useSessionStore } from '../../store/session.js'
import { cn, fmtArgs, fmtDuration, truncate } from '../../lib/utils/cn.js'
import { EditFileDiff } from './EditFileDiff.js'

interface Props {
  tc: ToolCall
}

export const ToolCallRow = ({ tc }: Props): React.ReactElement => {
  const expandedMap = useSessionStore((s) => s.toolCallExpandedById)
  const toggle = useSessionStore((s) => s.toggleToolCallExpand)
  const expanded = effectiveToolCallExpanded(tc, expandedMap)
  const argsStr = fmtArgs(tc.args, 72)
  const nChars = tc.result?.length ?? tc.error?.length ?? 0
  const summary =
    tc.status === 'error'
      ? `${tc.tool}(${argsStr}) · error`
      : nChars > 0
        ? `${tc.tool}(${argsStr}) · ${nChars} chars`
        : `${tc.tool}(${argsStr})`

  return (
    <div className="flex flex-col gap-0.5">
      <button
        type="button"
        onClick={() => toggle(tc.toolCallId)}
        className={cn(
          'flex items-center gap-1.5 text-xs text-left rounded-md px-1 py-0.5 -mx-1',
          'hover:bg-neutral-800/60 focus:outline-none focus-visible:ring-1 focus-visible:ring-indigo-500',
          tc.status === 'pending' ? 'text-yellow-400' : tc.status === 'done' ? 'text-neutral-400' : 'text-red-400',
        )}
      >
        {expanded ? <ChevronDown size={12} className="shrink-0 text-neutral-500" /> : <ChevronRight size={12} className="shrink-0 text-neutral-500" />}
        {tc.status === 'done' && <CheckCircle size={10} className="text-emerald-400 shrink-0" />}
        {tc.status === 'error' && <XCircle size={10} className="text-red-400 shrink-0" />}
        {tc.status === 'pending' && <Loader2 size={10} className="text-yellow-400 shrink-0 animate-spin" />}
        <Wrench size={10} className="text-neutral-500 shrink-0" />
        <span className="font-mono text-neutral-300">{summary}</span>
        {tc.durationMs != null && <span className="text-neutral-600">{fmtDuration(tc.durationMs)}</span>}
      </button>
      {expanded && tc.status === 'done' && tc.result && (
        <pre className="ml-5 text-xs text-neutral-500 whitespace-pre-wrap wrap-break-word max-h-40 overflow-y-auto border-l border-neutral-800 pl-2">
          {truncate(tc.result, 4000)}
        </pre>
      )}
      {expanded && tc.status === 'error' && tc.error && (
        <pre className="ml-5 text-xs text-red-400/90 whitespace-pre-wrap wrap-break-word max-h-32 overflow-y-auto border-l border-red-900/50 pl-2">
          {truncate(tc.error, 2000)}
        </pre>
      )}
      {expanded && <EditFileDiff toolCall={tc} />}
    </div>
  )
}
