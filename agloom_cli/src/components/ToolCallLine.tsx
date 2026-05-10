/**
 * ToolCallLine — renders a single tool call + its result inline.
 * Used in both CompletedTurnCard (static) and ActiveTurn (live).
 */

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
  /** If true, show the result/error body below the call line */
  showResult?: boolean
}

export function ToolCallLine({ tc, showResult = true }: Props): React.ReactElement {
  const icon = STATUS_ICON[tc.status]
  const color = STATUS_COLOR[tc.status]
  const argsStr = fmtArgs(tc.args, 55)

  return (
    <Box flexDirection="column" marginLeft={2}>
      {/* Call line */}
      <Box>
        <Text color={color as Parameters<typeof Text>[0]['color']}>{icon} </Text>
        <Text bold>{tc.tool}</Text>
        <Text color="gray"> {argsStr}</Text>
        {tc.durationMs !== undefined && (
          <Text color="gray" dimColor>
            {' '}
            {fmtDuration(tc.durationMs)}
          </Text>
        )}
      </Box>

      {/* Result / error body */}
      {showResult && tc.status === 'done' && tc.result && (
        <Box marginLeft={3}>
          <Text color="gray" dimColor>
            {truncate(tc.result, 120)}
          </Text>
        </Box>
      )}
      {showResult && tc.status === 'error' && tc.error && (
        <Box marginLeft={3}>
          <Text color="red" dimColor>
            {truncate(tc.error, 120)}
          </Text>
        </Box>
      )}
    </Box>
  )
}
