/** One tool call row (summary + optional expanded body). */
import React from 'react'
import { Box, Text } from 'ink'
import { Badge } from '@inkjs/ui'
import type { ToolCall } from '../store/session.js'
import { useSessionStore } from '../store/session.js'
import { fmtArgs, fmtDuration, stripAgloomToolResultEnvelope } from '../utils/format.js'

const MAX_PLAIN_RESULT_LINES = 200

const clipLine = (line: string, maxCols: number): string => {
  if (line.length <= maxCols) return line
  return `${line.slice(0, Math.max(8, maxCols - 1))}…`
}

const looksLikeUnifiedDiff = (text: string): boolean => {
  if (text.length < 40) return false
  const head = text.slice(0, 8000)
  if (/^diff --git /m.test(head)) return true
  if (/^--- [^\n]+\n\+\+\+ /m.test(head)) return true
  let plus = 0
  let minus = 0
  for (const ln of head.split('\n')) {
    if (ln.startsWith('+') && !ln.startsWith('+++')) plus += 1
    if (ln.startsWith('-') && !ln.startsWith('---')) minus += 1
  }
  return plus >= 2 && minus >= 2 && plus + minus >= 6
}

const diffLineColor = (line: string): 'green' | 'red' | 'magenta' | 'cyan' | 'gray' => {
  if (line.startsWith('+') && !line.startsWith('+++')) return 'green'
  if (line.startsWith('-') && !line.startsWith('---')) return 'red'
  if (line.startsWith('@@')) return 'magenta'
  if (line.startsWith('diff --git')) return 'cyan'
  return 'gray'
}

const STATUS_ICON: Record<ToolCall['status'], string> = {
  pending: '○',
  done: '✓',
  error: '✗',
}

const STATUS_BADGE_COLOR: Record<ToolCall['status'], 'yellow' | 'green' | 'red'> = {
  pending: 'yellow',
  done: 'green',
  error: 'red',
}

interface Props {
  tc: ToolCall
  /** When true, render full (truncated) result / error body below the summary line. */
  expanded: boolean
}

export const ToolCallLine = ({ tc, expanded }: Props): React.ReactElement => {
  const mainColumnWidth = useSessionStore((s) => s.mainColumnWidth)
  const icon = STATUS_ICON[tc.status]
  const badgeColor = STATUS_BADGE_COLOR[tc.status]
  const displayResult = tc.result ? stripAgloomToolResultEnvelope(tc.result) : tc.result
  const argsStr = fmtArgs(tc.args, 72)
  const chevron = expanded ? '▼' : '▶'
  const nChars = displayResult?.length ?? tc.error?.length ?? 0
  const summary =
    tc.status === 'error'
      ? `${chevron} ${tc.tool}(${argsStr})`
      : nChars > 0
        ? `${chevron} ${tc.tool}(${argsStr}) · ${nChars} chars`
        : `${chevron} ${tc.tool}(${argsStr})`

  return (
    <Box flexDirection="column" marginLeft={2}>
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        <Text color={badgeColor}>{icon} </Text>
        <Badge color={badgeColor}>{tc.status}</Badge>
        <Text dimColor>{summary}</Text>
        {tc.durationMs !== undefined && (
          <Text color="gray" dimColor>
            {' '}
            {fmtDuration(tc.durationMs)}
          </Text>
        )}
      </Box>

      {expanded && tc.status === 'done' && displayResult && looksLikeUnifiedDiff(displayResult) && (
        <Box marginLeft={3} flexDirection="column">
          {displayResult.split('\n').slice(0, 120).map((line, i) => {
            const c = diffLineColor(line)
            const shown = line.length > 200 ? `${line.slice(0, 197)}…` : line
            return (
              <Text key={i} color={c} dimColor={c === 'gray'}>
                {shown}
              </Text>
            )
          })}
        </Box>
      )}
      {expanded && tc.status === 'done' && displayResult && !looksLikeUnifiedDiff(displayResult) && (() => {
        const cols = Math.max(40, mainColumnWidth - 4)
        const lines = displayResult.split('\n')
        const slice = lines.slice(0, MAX_PLAIN_RESULT_LINES)
        const omitted = lines.length - slice.length
        return (
          <Box marginLeft={3} flexDirection="column">
            {slice.map((line, i) => (
              <Text key={i} color="gray" dimColor wrap="truncate-end">
                {clipLine(line, cols)}
              </Text>
            ))}
            {omitted > 0 ? (
              <Text color="gray" dimColor>
                … {omitted} more line{omitted === 1 ? '' : 's'} (Ctrl+T / /tools to collapse)
              </Text>
            ) : null}
          </Box>
        )
      })()}
      {expanded && tc.status === 'error' && tc.error && (
        <Box marginLeft={3} flexDirection="column">
          {tc.error.split('\n').slice(0, 40).map((line, i) => (
            <Text key={i} color="red" dimColor wrap="truncate-end">
              {clipLine(line, Math.max(40, mainColumnWidth - 4))}
            </Text>
          ))}
        </Box>
      )}
    </Box>
  )
}
