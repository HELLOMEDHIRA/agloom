/** Full reasoning / thinking trace (always visible, not collapsible). */
import React from 'react'
import { Brain } from 'lucide-react'
import type { ThinkingStep } from '../../store/session.js'
import { fmtDuration } from '../../lib/utils/cn.js'

interface Props {
  steps: ThinkingStep[]
}

export const ThinkingTrace = ({ steps }: Props): React.ReactElement | null => {
  if (steps.length === 0) return null

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-neutral-500">
        Reasoning
      </div>
      {steps.map((s) => (
        <div key={s.id} className="flex flex-col gap-0.5 text-xs text-neutral-500">
          <div className="flex items-center gap-1.5">
            <Brain size={9} className="text-neutral-600 shrink-0" />
            <span className="text-neutral-400">{s.label ?? s.step}</span>
            {s.elapsedMs != null && (
              <span className="text-neutral-700">{fmtDuration(s.elapsedMs)}</span>
            )}
          </div>
          {s.detail ? (
            <pre className="ml-4 text-[11px] text-neutral-500 whitespace-pre-wrap wrap-break-word border-l border-neutral-800 pl-2 leading-relaxed">
              {s.detail}
            </pre>
          ) : null}
        </div>
      ))}
    </div>
  )
}
