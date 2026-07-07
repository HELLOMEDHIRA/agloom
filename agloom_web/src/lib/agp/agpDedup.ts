import type { AGPEvent } from './types.js'
import type { CompletedTurn, MetricTokensSlice, SessionStore } from '../../store/session.js'

/** Event types that must not be re-applied when the same ``id``/``seq`` is replayed. */
const REPLAY_DEDUP_TYPES = new Set<string>([
  'message.user',
  'message.assistant',
  'metric.cost',
  'metric.tokens',
  'harness.synced',
  'harness.task.updated',
])

export const shouldSkipReplayEvent = (s: SessionStore, evt: AGPEvent): boolean => {
  const seen = s.seenEventIds ?? []
  if (seen.includes(evt.id)) return true
  if (!REPLAY_DEDUP_TYPES.has(evt.type)) return false
  const seq = evt.seq ?? 0
  if (seq > 0 && seq <= (s.replayBaselineSeq ?? 0)) return true
  return false
}

export const trackAgpEnvelope = (s: SessionStore, evt: AGPEvent): SessionStore => ({
  ...s,
  seenEventIds: [...(s.seenEventIds ?? []), evt.id],
  lastSeenSeq: Math.max(s.lastSeenSeq ?? 0, evt.seq ?? 0),
})

export const replayResumeReset = (replayedFromSeq?: number): Partial<SessionStore> => ({
  completedTurns: [] as CompletedTurn[],
  harnessLedgerTasks: null,
  harnessLedgerRevision: 0,
  totalCostUsd: 0,
  totalInputTokens: 0,
  totalOutputTokens: 0,
  turnInputTokens: 0,
  turnOutputTokens: 0,
  metricsHistory: [] as MetricTokensSlice[],
  lastMetricTokensSeq: 0,
  lastMetricCostSeq: 0,
  seenEventIds: [],
  lastSeenSeq: replayedFromSeq ?? 0,
  replayBaselineSeq: replayedFromSeq ?? 0,
})
