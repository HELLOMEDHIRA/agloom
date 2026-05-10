/**
 * ChatPane — scrollable conversation + active streaming turn + input bar.
 * Pure React, AGP-driven. No polling, no REST calls.
 */
import React, { useRef, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useSessionStore } from '../../store/session.js'
import type { AGPClient } from '../../lib/agp/client.js'
import { CompletedTurnCard } from './CompletedTurnCard.js'
import { StreamingTurn } from './StreamingTurn.js'
import { HITLGate } from './HITLGate.js'
import { ChatInput } from './ChatInput.js'

interface Props {
  client: AGPClient
  thread: string
}

export function ChatPane({ client, thread }: Props): React.ReactElement {
  const completedTurns = useSessionStore((s) => s.completedTurns)
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const hitlQueue = useSessionStore((s) => s.hitlQueue)
  const status = useSessionStore((s) => s.status)
  const errorMessage = useSessionStore((s) => s.errorMessage)

  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [completedTurns.length, activeTurn?.streamedTokens])

  const handleSubmit = (text: string) => {
    if (!text.trim()) return
    client.invoke(text.trim(), thread)
  }

  return (
    <div className="flex flex-col h-full">
      {/* ── Message history ── */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">

        {/* Empty state */}
        {completedTurns.length === 0 && !activeTurn && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <p className="text-2xl font-semibold text-white">What can I help you with?</p>
            <p className="text-sm text-neutral-500 max-w-sm">
              Powered by LangGraph · AGP streaming · distributed execution
            </p>
          </div>
        )}

        {/* Completed turns */}
        {completedTurns.map((turn) => (
          <CompletedTurnCard key={turn.id} turn={turn} />
        ))}

        {/* Active streaming turn */}
        <AnimatePresence>
          {activeTurn && (
            <motion.div
              key="active"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <StreamingTurn turn={activeTurn} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* HITL gate */}
        <AnimatePresence>
          {status === 'hitl' && hitlQueue[0] && (
            <motion.div
              key="hitl"
              initial={{ opacity: 0, scale: 0.97 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
            >
              <HITLGate request={hitlQueue[0]} onRespond={(id, decision, text) => client.hitlRespond(id, decision, text)} />
            </motion.div>
          )}
        </AnimatePresence>

        {/* Transient error */}
        {errorMessage && status !== 'error' && (
          <div className="text-sm text-red-400 px-4 py-2 rounded-lg bg-red-950/40 border border-red-900/50">
            ⚠ {errorMessage}
          </div>
        )}

        {/* Fatal error */}
        {status === 'error' && errorMessage && (
          <div className="text-sm text-red-300 px-4 py-3 rounded-xl bg-red-950/50 border border-red-800">
            <strong>Fatal:</strong> {errorMessage}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ── */}
      <ChatInput
        onSubmit={handleSubmit}
        onCancel={() => client.cancel(thread)}
        disabled={status === 'hitl'}
        isRunning={status === 'running' || status === 'thinking'}
      />
    </div>
  )
}
