/** One tool call row — summary plus full result body (always visible, untruncated). */
import React from 'react'
import { Box, Text } from 'ink'
import { Badge } from '@inkjs/ui'
import type { ToolCall } from '../store/session.js'
import { fmtArgs, fmtDuration, stripAgloomToolResultEnvelope } from '../utils/format.js'

const looksLikeUnifiedDiff = (text: string): boolean => {
  if (text.length < 40) return false
  const head = text
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
}

export const ToolCallLine = ({ tc }: Props): React.ReactElement => {
  const icon = STATUS_ICON[tc.status]
  const badgeColor = STATUS_BADGE_COLOR[tc.status]
  const displayResult = tc.result ? stripAgloomToolResultEnvelope(tc.result) : tc.result
  const argsStr = fmtArgs(tc.args, 10_000)
  const nChars = displayResult?.length ?? tc.error?.length ?? 0
  const summary =
    tc.status === 'error'
      ? `${tc.tool}(${argsStr})`
      : nChars > 0
        ? `${tc.tool}(${argsStr}) · ${nChars} chars`
        : `${tc.tool}(${argsStr})`

  return (
    <Box flexDirection="column" marginLeft={2}>
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        <Text color={badgeColor}>{icon} </Text>
        <Badge color={badgeColor}>{tc.status}</Badge>
        <Text dimColor wrap="wrap">
          {summary}
        </Text>
        {tc.durationMs !== undefined && (
          <Text color="gray" dimColor>
            {' '}
            {fmtDuration(tc.durationMs)}
          </Text>
        )}
      </Box>

      {tc.status === 'done' && displayResult && looksLikeUnifiedDiff(displayResult) && (
        <Box marginLeft={3} flexDirection="column">
          {displayResult.split('\n').map((line, i) => {
            const c = diffLineColor(line)
            return (
              <Text key={i} color={c} dimColor={c === 'gray'} wrap="wrap">
                {line}
              </Text>
            )
          })}
        </Box>
      )}
      {tc.status === 'done' && displayResult && !looksLikeUnifiedDiff(displayResult) && (
        <Box marginLeft={3} flexDirection="column">
          {displayResult.split('\n').map((line, i) => (
            <Text key={i} color="gray" dimColor wrap="wrap">
              {line}
            </Text>
          ))}
        </Box>
      )}
      {tc.status === 'error' && tc.error && (
        <Box marginLeft={3} flexDirection="column">
          {tc.error.split('\n').map((line, i) => (
            <Text key={i} color="red" dimColor wrap="wrap">
              {line}
            </Text>
          ))}
        </Box>
      )}
    </Box>
  )
}
