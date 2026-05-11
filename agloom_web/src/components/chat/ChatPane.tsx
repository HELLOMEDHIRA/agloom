/** Main chat column: history, streaming turn, HITL, input. */
import React, { useRef, useEffect, useState } from 'react'
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
  workspaceSessionId: string
}

type BudgetLast = { dimension: string; used: number; limit: number }

const BudgetExhaustedDialog = ({
  budgetLast,
  client,
  onApplied,
}: {
  budgetLast: BudgetLast
  client: AGPClient
  onApplied: () => void
}): React.ReactElement => {
  const lim = budgetLast.limit
  const [raiseTok, setRaiseTok] = useState(() =>
    budgetLast.dimension === 'tokens' && lim > 0 ? String(Math.ceil(lim * 1.25)) : '',
  )
  const [raiseUsd, setRaiseUsd] = useState(() =>
    budgetLast.dimension === 'cost_usd' && lim > 0 ? String((lim * 1.25).toFixed(2)) : '',
  )

  const applyBudgetRaise = (): void => {
    const tok = raiseTok.trim() ? parseInt(raiseTok.trim(), 10) : NaN
    const usd = raiseUsd.trim() ? parseFloat(raiseUsd.trim()) : NaN
    const data: { budget_token_limit?: number; budget_cost_usd_limit?: number } = {}
    if (!Number.isNaN(tok) && tok > 0) data.budget_token_limit = tok
    if (!Number.isNaN(usd) && usd > 0) data.budget_cost_usd_limit = usd
    if (Object.keys(data).length === 0) return
    client.configSet(data)
    onApplied()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div
        role="dialog"
        aria-modal="true"
        className="max-w-md w-full rounded-2xl border border-red-900/60 bg-neutral-950 p-5 shadow-xl"
      >
        <h2 className="text-lg font-semibold text-red-200 mb-2">Session budget exhausted</h2>
        <p className="text-sm text-neutral-300 mb-4">
          Invokes are blocked until you raise the cap via{' '}
          <code className="text-indigo-300">command.config.set</code>. Dimension:{' '}
          <strong>{budgetLast.dimension}</strong> — used {budgetLast.used} (limit {budgetLast.limit}).
        </p>
        <div className="flex flex-col gap-3 mb-4">
          <label className="text-xs text-neutral-500">
            New token limit (total cumulative)
            <input
              value={raiseTok}
              onChange={(e) => setRaiseTok(e.target.value)}
              placeholder="e.g. 200000"
              className="mt-1 w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-white"
            />
          </label>
          <label className="text-xs text-neutral-500">
            New USD cost limit (cumulative)
            <input
              value={raiseUsd}
              onChange={(e) => setRaiseUsd(e.target.value)}
              placeholder="e.g. 5.00"
              className="mt-1 w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-white"
            />
          </label>
        </div>
        <div className="flex justify-end">
          <button
            type="button"
            onClick={applyBudgetRaise}
            className="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-500"
          >
            Apply new limits
          </button>
        </div>
      </div>
    </div>
  )
}

export const ChatPane = ({ client, thread, workspaceSessionId }: Props): React.ReactElement => {
  const completedTurns = useSessionStore((s) => s.completedTurns)
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const hitlQueue = useSessionStore((s) => s.hitlQueue)
  const status = useSessionStore((s) => s.status)
  const errorMessage = useSessionStore((s) => s.errorMessage)
  const pendingAttachmentPaths = useSessionStore((s) => s.pendingAttachmentPaths)
  const clearPendingAttachments = useSessionStore((s) => s.clearPendingAttachments)
  const budgetUi = useSessionStore((s) => s.budgetUi)
  const budgetLast = useSessionStore((s) => s.budgetLast)
  const setBudgetUiOk = useSessionStore((s) => s.setBudgetUiOk)

  const bottomRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [completedTurns.length, activeTurn?.streamedTokens])

  const handleSubmit = (text: string) => {
    if (!text.trim()) return
    const paths = pendingAttachmentPaths
    const prefix =
      paths.length > 0
        ? `The following files were uploaded into the agent working directory (paths relative to the CLI tools root):\n${paths.map((p) => `- ${p}`).join('\n')}\n\n`
        : ''
    clearPendingAttachments()
    client.invoke(prefix + text.trim(), thread)
  }

  return (
    <div className="flex flex-col h-full relative">
      {budgetUi === 'approaching' && (
        <div className="shrink-0 mx-4 mt-3 px-3 py-2 rounded-lg border border-amber-600/50 bg-amber-950/40 text-amber-100 text-sm">
          Session budget is above ~80% ({budgetLast?.dimension ?? 'limit'}
          {budgetLast != null ? ` · ${budgetLast.used} / ${budgetLast.limit}` : ''}). Further usage may hit the cap.
        </div>
      )}

      {budgetUi === 'exhausted' && budgetLast != null && (
        <BudgetExhaustedDialog
          key={`${budgetLast.dimension}-${budgetLast.limit}-${budgetLast.used}`}
          budgetLast={budgetLast}
          client={client}
          onApplied={() => {
            setBudgetUiOk()
          }}
        />
      )}

      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">

        {completedTurns.length === 0 && !activeTurn && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
            <p className="text-2xl font-semibold text-neutral-900 dark:text-white">What can I help you with?</p>
            <p className="text-sm text-neutral-600 dark:text-neutral-500 max-w-sm">
              Powered by LangGraph · AGP streaming · distributed execution
            </p>
          </div>
        )}

        {completedTurns.map((turn) => (
          <CompletedTurnCard key={turn.id} turn={turn} />
        ))}

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

        {errorMessage && status !== 'error' && (
          <div className="text-sm text-red-400 px-4 py-2 rounded-lg bg-red-950/40 border border-red-900/50">
            ⚠ {errorMessage}
          </div>
        )}

        {status === 'error' && errorMessage && (
          <div className="text-sm text-red-300 px-4 py-3 rounded-xl bg-red-950/50 border border-red-800">
            <strong>Fatal:</strong> {errorMessage}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <ChatInput
        client={client}
        workspaceSessionId={workspaceSessionId}
        onSubmit={handleSubmit}
        onCancel={() => client.cancel(thread)}
        onAttachFiles={(files) => {
          for (const f of files) {
            const reader = new FileReader()
            reader.onload = () => {
              const r = reader.result
              if (typeof r !== 'string') return
              const i = r.indexOf(',')
              const b64 = i >= 0 ? r.slice(i + 1) : r
              client.attachFile(f.name, b64, thread)
            }
            reader.readAsDataURL(f)
          }
        }}
        pendingAttachmentPaths={pendingAttachmentPaths}
        disabled={status === 'hitl' || budgetUi === 'exhausted'}
        isRunning={status === 'running' || status === 'thinking'}
      />
    </div>
  )
}
