/** One tool call row (summary + optional expanded body). */
import React from 'react'
import { Box, Text } from 'ink'
import type { ToolCall } from '../store/session.js'
import { truncate, fmtArgs, fmtDuration } from '../utils/format.js'

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

      {expanded && tc.status === 'done' && tc.result && (
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
