/** SessionSidebar — left panel showing past turns in the current session.
 * Displays a scrollable list of completed turns so the user can see the conversation history at a glance. Each entry shows the first line of the user message and the pattern that was used, plus a timestamp.
 */
import React from 'react'
import { useSessionStore } from '../../store/session.js'
import { MessageSquare, Cpu } from 'lucide-react'

export const SessionSidebar = (): React.ReactElement => {
  const completedTurns = useSessionStore((s) => s.completedTurns)
  const sessionId = useSessionStore((s) => s.sessionId)
  const status = useSessionStore((s) => s.status)

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-neutral-800 shrink-0">
        <div className="flex items-center gap-2">
          <MessageSquare size={13} className="text-indigo-400" />
          <span className="text-xs font-medium text-neutral-300">Session</span>
        </div>
        {sessionId && (
          <p className="text-[10px] text-neutral-600 mt-0.5 font-mono whitespace-pre-wrap break-all">{sessionId}</p>
        )}
      </div>

      {/* Turn list */}
      <div className="flex-1 overflow-y-auto">
        {completedTurns.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-24 gap-2 text-neutral-600 px-3">
            <MessageSquare size={18} />
            <span className="text-xs text-center">No turns yet</span>
          </div>
        ) : (
          <ul className="py-1">
            {completedTurns.map((turn) => (
              <li
                key={turn.id}
                className="px-3 py-2 hover:bg-neutral-900 transition-colors group"
              >
                {/* User message preview */}
                <p className="text-xs text-neutral-300 whitespace-pre-wrap break-words leading-snug">
                  {turn.userMessage}
                </p>
                {/* Meta row */}
                <div className="flex items-center gap-2 mt-0.5">
                  {turn.pattern && (
                    <span className="flex items-center gap-0.5 text-[10px] text-indigo-400">
                      <Cpu size={9} />
                      {turn.pattern}
                    </span>
                  )}
                  {turn.timestamp && (
                    <span className="text-[10px] text-neutral-600 ml-auto">
                      {turn.timestamp instanceof Date
                        ? turn.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                        : ''}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {/* Active turn indicator */}
        {status === 'thinking' && (
          <div className="flex items-center gap-2 px-3 py-2 border-t border-neutral-800 mt-1">
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
            <span className="text-xs text-neutral-500">Processing…</span>
          </div>
        )}
      </div>
    </div>
  )
}
