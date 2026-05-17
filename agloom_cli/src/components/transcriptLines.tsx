/** Flatten completed turns into one Ink row per scroll step (for ``ScrollableColumn``). */

import React from 'react'
import { Text } from 'ink'
import type { CompletedTurn, ToolCall } from '../store/session.js'
import { effectiveToolCallExpanded } from '../store/session.js'
import { fmtArgs, fmtDuration, stripAgloomToolResultEnvelope, truncate } from '../utils/format.js'
import { wrapTextLines } from '../utils/wrapLines.js'
import type { ThinkingStep } from '../store/session.js'

const MAX_TOOL_BODY_LINES = 48

const clipLine = (line: string, maxCols: number): string => {
  if (line.length <= maxCols) return line
  return `${line.slice(0, Math.max(8, maxCols - 1))}…`
}

const pushThinkingLines = (
  out: React.ReactElement[],
  steps: ThinkingStep[],
  turnId: string,
  detailCap: number,
): void => {
  for (const s of steps) {
    const head = s.label ?? s.step
    const timing = s.elapsedMs != null ? ` · ${s.elapsedMs}ms` : ''
    out.push(
      <Text key={`${turnId}-th-${s.id}-h`} color="gray" dimColor wrap="truncate-end">
        {head}
        {timing}
      </Text>,
    )
    if (s.detail) {
      out.push(
        <Text key={`${turnId}-th-${s.id}-d`} color="gray" dimColor wrap="truncate-end">
          {truncate(s.detail, detailCap)}
        </Text>,
      )
    }
  }
}

const pushToolLines = (
  out: React.ReactElement[],
  tc: ToolCall,
  turnId: string,
  expanded: boolean,
  cols: number,
): void => {
  const icon = tc.status === 'done' ? '✓' : tc.status === 'error' ? '✗' : '○'
  const argsStr = fmtArgs(tc.args, 72)
  const nChars = tc.result?.length ?? tc.error?.length ?? 0
  const summary =
    tc.status === 'error'
      ? `${icon} ${tc.tool}(${argsStr})`
      : nChars > 0
        ? `${icon} ${tc.tool}(${argsStr}) · ${nChars} chars`
        : `${icon} ${tc.tool}(${argsStr})`
  const dur = tc.durationMs !== undefined ? ` ${fmtDuration(tc.durationMs)}` : ''
  out.push(
    <Text key={`${turnId}-tc-${tc.id}-s`} color="gray" dimColor wrap="truncate-end">
      {summary}
      {dur}
    </Text>,
  )
  if (!expanded) return
  const body = tc.status === 'error' ? tc.error : tc.result ? stripAgloomToolResultEnvelope(tc.result) : ''
  if (!body) return
  for (const [i, line] of body.split('\n').slice(0, MAX_TOOL_BODY_LINES).entries()) {
    out.push(
      <Text key={`${turnId}-tc-${tc.id}-b${i}`} color="gray" dimColor wrap="truncate-end">
        {clipLine(line, cols)}
      </Text>,
    )
  }
}

export const flattenCompletedTurnLines = (
  turn: CompletedTurn,
  opts: {
    hideThinkingTrace: boolean
    width: number
    toolCallExpandedById: Record<string, boolean>
  },
): React.ReactElement[] => {
  const { hideThinkingTrace, width, toolCallExpandedById } = opts
  const cols = Math.max(40, width - 4)
  const detailCap = Math.max(120, width * 3)
  const out: React.ReactElement[] = []

  const userRows = wrapTextLines(turn.userMessage, cols)
  userRows.forEach((row, i) => {
    out.push(
      <Text key={`${turn.id}-user-${i}`} wrap="truncate-end">
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

  if (!hideThinkingTrace && turn.thinkingSteps.length > 0) {
    pushThinkingLines(out, turn.thinkingSteps, turn.id, detailCap)
  }

  for (const w of turn.workers) {
    out.push(
      <Text key={`${turn.id}-w-${w.id}`} color="gray" dimColor wrap="truncate-end">
        worker {w.name ?? w.workerId} · {w.status}
      </Text>,
    )
  }

  for (const tc of turn.toolCalls) {
    pushToolLines(out, tc, turn.id, effectiveToolCallExpanded(tc, toolCallExpandedById), cols)
  }

  if (turn.assistantMessage.trim()) {
    let rowIdx = 0
    for (const block of turn.assistantMessage.split('\n')) {
      for (const row of wrapTextLines(block, cols)) {
        out.push(
          <Text key={`${turn.id}-as-${rowIdx}`} wrap="truncate-end">
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
  if (turn.tokens !== undefined) meta.push(`${turn.tokens} tok`)
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
