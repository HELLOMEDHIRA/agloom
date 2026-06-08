/** Flatten completed turns into one Ink row per scroll step (for ``ScrollableColumn``). */

import React from 'react'
import { Text } from 'ink'
import type { CompletedTurn, ToolCall } from '../store/session.js'
import { fmtArgs, fmtDuration, stripAgloomToolResultEnvelope } from '../utils/format.js'
import { stripStrayToolJsonFromStream } from '../utils/strayToolJson.js'
import { wrapTextLines } from '../utils/wrapLines.js'
import type { ThinkingStep } from '../store/session.js'

const pushThinkingLines = (
  out: React.ReactElement[],
  steps: ThinkingStep[],
  turnId: string,
  detailCols: number,
): void => {
  for (const s of steps) {
    const head = s.label ?? s.step
    const timing = s.elapsedMs != null ? ` · ${s.elapsedMs}ms` : ''
    out.push(
      <Text key={`${turnId}-th-${s.id}-h`} color="gray" dimColor wrap="wrap">
        {head}
        {timing}
      </Text>,
    )
    if (s.detail) {
      wrapTextLines(s.detail, detailCols).forEach((row, i) => {
        out.push(
          <Text key={`${turnId}-th-${s.id}-d-${i}`} color="gray" dimColor wrap="wrap">
            {row}
          </Text>,
        )
      })
    }
  }
}

const pushToolLines = (
  out: React.ReactElement[],
  tc: ToolCall,
  turnId: string,
): void => {
  const icon = tc.status === 'done' ? '✓' : tc.status === 'error' ? '✗' : '○'
  const argsStr = fmtArgs(tc.args, 10_000)
  const nChars = tc.result?.length ?? tc.error?.length ?? 0
  const summary =
    tc.status === 'error'
      ? `${icon} ${tc.tool}(${argsStr})`
      : nChars > 0
        ? `${icon} ${tc.tool}(${argsStr}) · ${nChars} chars`
        : `${icon} ${tc.tool}(${argsStr})`
  const dur = tc.durationMs !== undefined ? ` ${fmtDuration(tc.durationMs)}` : ''
  out.push(
    <Text key={`${turnId}-tc-${tc.id}-s`} color="gray" dimColor wrap="wrap">
      {summary}
      {dur}
    </Text>,
  )
  const body = tc.status === 'error' ? tc.error : tc.result ? stripAgloomToolResultEnvelope(tc.result) : ''
  if (!body) return
  for (const [i, line] of body.split('\n').entries()) {
    out.push(
      <Text key={`${turnId}-tc-${tc.id}-b${i}`} color="gray" dimColor wrap="wrap">
        {line}
      </Text>,
    )
  }
}

export const flattenCompletedTurnLines = (
  turn: CompletedTurn,
  opts: {
    width: number
    toolNames?: string[] | null
  },
): React.ReactElement[] => {
  const { width, toolNames } = opts
  const cols = Math.max(40, width - 4)
  const detailCols = cols
  const out: React.ReactElement[] = []

  const userRows = wrapTextLines(turn.userMessage, cols)
  userRows.forEach((row, i) => {
    out.push(
      <Text key={`${turn.id}-user-${i}`} wrap="wrap">
        {i === 0 ? (
          <>
            <Text bold color="cyan">
              ❯{' '}
            </Text>
            <Text bold>{row}</Text>
          </>
        ) : (
          <Text>{'  '}{row}</Text>
        )}
      </Text>,
    )
  })

  if (turn.thinkingSteps.length > 0) {
    out.push(
      <Text key={`${turn.id}-th-head`} color="gray" dimColor bold>
        Trace
      </Text>,
    )
    pushThinkingLines(out, turn.thinkingSteps, turn.id, detailCols)
  }

  for (const w of turn.workers) {
    out.push(
      <Text key={`${turn.id}-w-${w.id}`} color="gray" dimColor wrap="wrap">
        worker {w.name ?? w.workerId} · {w.status}
        {w.task ? ` — ${w.task}` : ''}
        {w.outputPreview ? ` — ${w.outputPreview}` : ''}
        {w.error ? ` — ${w.error}` : ''}
      </Text>,
    )
  }

  for (const tc of turn.toolCalls) {
    pushToolLines(out, tc, turn.id)
  }

  const allowedTools = new Set((toolNames ?? []).map((n) => n.trim()).filter(Boolean))
  const assistantBody = stripStrayToolJsonFromStream(
    stripAgloomToolResultEnvelope(turn.assistantMessage),
    allowedTools,
    { permissive: allowedTools.size === 0 },
  )

  if (assistantBody.trim()) {
    let rowIdx = 0
    for (const block of assistantBody.split('\n')) {
      for (const row of wrapTextLines(block, cols)) {
        out.push(
          <Text key={`${turn.id}-as-${rowIdx}`} wrap="wrap">
            {row}
          </Text>,
        )
        rowIdx += 1
      }
    }
  } else {
    out.push(
      <Text key={`${turn.id}-as-empty`} color="yellow">
        No assistant text on wire
      </Text>,
    )
  }

  const meta: string[] = []
  if (turn.pattern) meta.push(turn.pattern)
  if (turn.tokens) meta.push(turn.tokens)
  if (meta.length > 0) {
    out.push(
      <Text key={`${turn.id}-meta`} color="gray" dimColor>
        {meta.join(' · ')}
      </Text>,
    )
  }

  out.push(
    <Text key={`${turn.id}-sep`} color="gray" dimColor>
      {'─'.repeat(Math.min(width - 2, 60))}
    </Text>,
  )

  return out
}
