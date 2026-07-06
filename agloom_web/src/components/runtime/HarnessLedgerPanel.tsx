/** Durable harness task ledger from ``harness.synced`` events. */
import React from 'react'
import { useSessionStore } from '../../store/session.js'

export const HarnessLedgerPanel = (): React.ReactElement => {
  const harnessEnabled = useSessionStore((s) => s.harnessEnabled)
  const tasks = useSessionStore((s) => s.harnessLedgerTasks)

  if (harnessEnabled === false) {
    return (
      <div className="p-4 text-sm text-neutral-500">
        Harness is off for this runtime (`--no-harness` or `--agent-store none`).
      </div>
    )
  }

  if (!tasks?.length) {
    return (
      <div className="p-4 text-sm text-neutral-500">
        No harness tasks yet. They appear after the turn planner seeds a ledger on a planning turn.
      </div>
    )
  }

  return (
    <div className="p-3 space-y-2 overflow-y-auto h-full">
      <p className="text-xs text-neutral-500 uppercase tracking-wide">Harness ledger</p>
      <ul className="space-y-2">
        {tasks.map((t) => (
          <li
            key={t.task_id}
            className="rounded-lg border border-neutral-800 bg-neutral-900/60 px-3 py-2 text-sm"
          >
            <div className="font-mono text-xs text-indigo-300">{t.task_id}</div>
            <div className="text-neutral-200 mt-1">{t.description}</div>
            <div className="text-xs text-neutral-500 mt-1">
              {[t.status, t.category, t.priority].filter(Boolean).join(' · ')}
              {t.verification_step_count != null ? ` · ${t.verification_step_count} checks` : ''}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
