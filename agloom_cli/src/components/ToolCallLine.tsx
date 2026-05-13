/** One tool call row (summary + optional expanded body). */
import React from 'react'
import { Box, Text } from 'ink'
import type { ToolCall } from '../store/session.js'
import { truncate, fmtArgs, fmtDuration } from '../utils/format.js'

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

const STATUS_COLOR: Record<ToolCall['status'], string> = {
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
  const icon = STATUS_ICON[tc.status]
  const color = STATUS_COLOR[tc.status]
  const argsStr = fmtArgs(tc.args, 72)
  const chevron = expanded ? '▼' : '▶'
  const nChars = tc.result?.length ?? tc.error?.length ?? 0
  const summary =
    tc.status === 'error'
      ? `${chevron} ${tc.tool}(${argsStr}) · error`
      : nChars > 0
        ? `${chevron} ${tc.tool}(${argsStr}) · ${nChars} chars`
        : `${chevron} ${tc.tool}(${argsStr})`

  return (
    <Box flexDirection="column" marginLeft={2}>
      <Box>
        <Text color={color as 'green' | 'yellow' | 'red'}>{icon} </Text>
        <Text dimColor>{summary}</Text>
        {tc.durationMs !== undefined && (
          <Text color="gray" dimColor>
            {' '}
            {fmtDuration(tc.durationMs)}
          </Text>
        )}
      </Box>

      {expanded && tc.status === 'done' && tc.result && looksLikeUnifiedDiff(tc.result) && (
        <Box marginLeft={3} flexDirection="column">
          {tc.result.split('\n').slice(0, 120).map((line, i) => {
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
      {expanded && tc.status === 'done' && tc.result && !looksLikeUnifiedDiff(tc.result) && (
        <Box marginLeft={3}>
          <Text color="gray" dimColor>
            {truncate(tc.result, 200)}
          </Text>
        </Box>
      )}
      {expanded && tc.status === 'error' && tc.error && (
        <Box marginLeft={3}>
          <Text color="red" dimColor>
            {truncate(tc.error, 200)}
          </Text>
        </Box>
      )}
    </Box>
  )
}
