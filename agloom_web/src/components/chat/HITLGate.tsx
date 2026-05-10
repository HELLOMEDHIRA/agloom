/**
 * HITLGate — approval prompt rendered inside the chat stream.
 */
import React, { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import type { HITLRequest } from '../../store/session.js'
import { cn } from '../../lib/utils/cn.js'

interface Props {
  request: HITLRequest
  onRespond: (requestId: string, decision: string, text?: string) => void
}

export function HITLGate({ request, onRespond }: Props): React.ReactElement {
  const [custom, setCustom] = useState('')

  const respond = (decision: string) => onRespond(request.requestId, decision)

  const BUTTONS: { label: string; decision: string; style: string }[] = [
    { label: 'Accept', decision: 'accept', style: 'bg-emerald-700 hover:bg-emerald-600 text-white' },
    { label: 'Deny',   decision: 'deny',   style: 'bg-red-800 hover:bg-red-700 text-white' },
    { label: 'Defer',  decision: 'defer',  style: 'bg-neutral-700 hover:bg-neutral-600 text-white' },
  ]

  return (
    <div className="rounded-xl border border-yellow-700/50 bg-yellow-950/30 p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <AlertTriangle size={14} className="text-yellow-400 shrink-0" />
        <span className="text-sm font-semibold text-yellow-300">HITL Gate — {request.kind}</span>
        {request.tool && <span className="text-xs text-neutral-500 ml-auto">{request.tool}</span>}
      </div>

      {request.detail && (
        <p className="text-sm text-neutral-300 leading-relaxed font-mono bg-neutral-900/60 px-3 py-2 rounded-lg">
          {request.detail}
        </p>
      )}

      {request.question && (
        <p className="text-sm text-neutral-400 italic">{request.question}</p>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {BUTTONS.map((b) => (
          <button key={b.decision} onClick={() => respond(b.decision)}
            className={cn('px-3 py-1.5 rounded-lg text-xs font-medium transition-colors', b.style)}>
            {b.label}
          </button>
        ))}

        <div className="flex items-center gap-1 ml-auto">
          <input
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="Custom response…"
            className="bg-neutral-900 border border-neutral-700 rounded-lg px-2 py-1 text-xs text-white placeholder-neutral-600 focus:outline-none focus:border-indigo-500 w-36"
            onKeyDown={(e) => { if (e.key === 'Enter' && custom.trim()) respond(custom.trim()) }}
          />
          {custom.trim() && (
            <button onClick={() => respond(custom.trim())} className="text-xs px-2 py-1 bg-neutral-700 rounded-lg hover:bg-neutral-600 text-white">Send</button>
          )}
        </div>
      </div>
    </div>
  )
}
