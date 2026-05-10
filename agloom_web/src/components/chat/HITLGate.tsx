/**
 * HITLGate — approval prompt rendered inside the chat stream.
 *
 * Mirrors AGP kinds: tool/pattern/worker gates (accept | reject | allowlist),
 * react_recovery (retry | stop), clarification (free-text via accept + text).
 */
import React, { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import type { HITLRequest } from '../../store/session.js'
import { cn } from '../../lib/utils/cn.js'

interface Props {
  request: HITLRequest
  onRespond: (requestId: string, decision: string, text?: string) => void
}

const labelForOption = (kind: string, option: string): string => {
  if (kind === 'react_recovery') {
    if (option === 'retry') return 'Retry'
    if (option === 'stop') return 'Stop'
  }
  if (option === 'accept') return 'Accept'
  if (option === 'reject') return 'Reject'
  if (option === 'allowlist') return 'Allowlist'
  return option.charAt(0).toUpperCase() + option.slice(1)
}

const btnClassForOption = (option: string): string => {
  if (option === 'accept' || option === 'retry' || option === 'allowlist') {
    return 'bg-emerald-800 hover:bg-emerald-700 text-white'
  }
  if (option === 'reject' || option === 'stop') {
    return 'bg-red-800 hover:bg-red-700 text-white'
  }
  return 'bg-neutral-700 hover:bg-neutral-600 text-white'
}

export const HITLGate = ({ request, onRespond }: Props): React.ReactElement => {
  const [custom, setCustom] = useState('')
  const [clarification, setClarification] = useState('')

  const respond = (decision: string, text?: string): void => {
    onRespond(request.requestId, decision, text)
  }

  if (request.kind === 'clarification') {
    return (
      <div className="rounded-xl border border-yellow-700/50 bg-yellow-950/30 p-4 flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <AlertTriangle size={14} className="text-yellow-400 shrink-0" />
          <span className="text-sm font-semibold text-yellow-300">HITL — clarification</span>
          {request.tool && <span className="text-xs text-neutral-500 ml-auto">{request.tool}</span>}
        </div>
        {request.detail && (
          <p className="text-sm text-neutral-300 leading-relaxed font-mono bg-neutral-900/60 px-3 py-2 rounded-lg">
            {request.detail}
          </p>
        )}
        {request.question && (
          <p className="text-sm text-neutral-200">{request.question}</p>
        )}
        <textarea
          value={clarification}
          onChange={(e) => setClarification(e.target.value)}
          placeholder="Your answer…"
          rows={3}
          className="bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm text-white placeholder-neutral-600 focus:outline-none focus:border-indigo-500 w-full resize-y min-h-[72px]"
        />
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => {
              const t = clarification.trim()
              if (!t) respond(request.default ?? 'cancelled')
              else respond('accept', t)
              setClarification('')
            }}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-700 hover:bg-indigo-600 text-white"
          >
            Submit answer
          </button>
          <button
            type="button"
            onClick={() => {
              respond(request.default ?? 'cancelled')
              setClarification('')
            }}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-neutral-700 hover:bg-neutral-600 text-white"
          >
            Cancel
          </button>
        </div>
      </div>
    )
  }

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
        {request.options.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => respond(opt)}
            className={cn('px-3 py-1.5 rounded-lg text-xs font-medium transition-colors', btnClassForOption(opt))}
          >
            {labelForOption(request.kind, opt)}
          </button>
        ))}

        <div className="flex items-center gap-1 ml-auto">
          <input
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
            placeholder="Custom decision…"
            className="bg-neutral-900 border border-neutral-700 rounded-lg px-2 py-1 text-xs text-white placeholder-neutral-600 focus:outline-none focus:border-indigo-500 w-36"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && custom.trim()) {
                respond(custom.trim())
                setCustom('')
              }
            }}
          />
          {custom.trim() ? (
            <button
              type="button"
              onClick={() => {
                respond(custom.trim())
                setCustom('')
              }}
              className="text-xs px-2 py-1 bg-neutral-700 rounded-lg hover:bg-neutral-600 text-white"
            >
              Send
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
