/** Tool call row — summary plus full result body (always visible). */
import React from 'react'
import { CheckCircle, XCircle, Wrench, Loader2 } from 'lucide-react'
import type { ToolCall } from '../../store/session.js'
import { fmtArgs, fmtDuration } from '../../lib/utils/cn.js'
import { stripAgloomToolResultEnvelope } from '../../lib/utils/assistantText.js'
import { EditFileDiff } from './EditFileDiff.js'

interface Props {
  tc: ToolCall
}

export const ToolCallRow = ({ tc }: Props): React.ReactElement => {
  const argsStr = fmtArgs(tc.args, 10_000)
  const nChars = tc.result?.length ?? tc.error?.length ?? 0
  const summary =
    tc.status === 'error'
      ? `${tc.tool}(${argsStr}) · error`
      : nChars > 0
        ? `${tc.tool}(${argsStr}) · ${nChars} chars`
        : `${tc.tool}(${argsStr})`

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1.5 text-xs">
        {tc.status === 'done' && <CheckCircle size={10} className="text-emerald-400 shrink-0" />}
        {tc.status === 'error' && <XCircle size={10} className="text-red-400 shrink-0" />}
        {tc.status === 'pending' && <Loader2 size={10} className="text-yellow-400 shrink-0 animate-spin" />}
        <Wrench size={10} className="text-neutral-500 shrink-0" />
        <span className="font-mono text-neutral-300">{summary}</span>
        {tc.durationMs != null && <span className="text-neutral-600">{fmtDuration(tc.durationMs)}</span>}
      </div>
      {tc.status === 'done' && tc.result && (
        <pre className="ml-5 text-xs text-neutral-500 whitespace-pre-wrap wrap-break-word border-l border-neutral-800 pl-2">
          {stripAgloomToolResultEnvelope(tc.result)}
        </pre>
      )}
      {tc.status === 'error' && tc.error && (
        <pre className="ml-5 text-xs text-red-400/90 whitespace-pre-wrap wrap-break-word border-l border-red-900/50 pl-2">
          {tc.error}
        </pre>
      )}
      <EditFileDiff toolCall={tc} />
    </div>
  )
}
