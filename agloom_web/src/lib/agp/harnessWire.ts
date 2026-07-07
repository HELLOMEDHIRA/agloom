/** Map harness wire payloads to session ledger rows. */

import type { HarnessLedgerTaskWire, HarnessPlanTaskWire } from './types.js'

export type HarnessLedgerRow = {
  task_id: string
  description: string
  category?: string
  status?: string
  priority?: string
  verification_step_count?: number
}

export const harnessPlanToLedgerRows = (plan: HarnessPlanTaskWire[] | undefined): HarnessLedgerRow[] =>
  (plan ?? []).map((t) => ({
    task_id: t.task_id,
    description: t.description,
    category: t.category,
    priority: t.priority,
    verification_step_count: t.verification_steps?.length,
  }))

export const harnessLedgerFromWire = (tasks: HarnessLedgerTaskWire[] | undefined): HarnessLedgerRow[] =>
  (tasks ?? []).map((t) => ({
    task_id: t.task_id,
    description: t.description,
    category: t.category,
    status: t.status,
    priority: t.priority,
    verification_step_count: t.verification_step_count,
  }))

/** Patch one ledger row after ``harness.task.updated`` (status / notes). */
export const patchHarnessLedgerTask = (
  tasks: HarnessLedgerRow[],
  update: { task_id: string; status: string; notes?: string },
): HarnessLedgerRow[] => {
  const idx = tasks.findIndex((t) => t.task_id === update.task_id)
  if (idx < 0) return tasks
  const next = [...tasks]
  const row = next[idx]!
  next[idx] = { ...row, status: update.status }
  return next
}
