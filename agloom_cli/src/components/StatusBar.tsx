/** StatusBar — bottom bar with session status, thread id, and Ctrl shortcuts. */

import React from 'react'
import { Box, Text, useWindowSize } from 'ink'
import { ProgressBar, StatusMessage } from '@inkjs/ui'
import { useSessionStore } from '../store/session.js'

const STATUS_LABEL: Record<string, string> = {
  idle: '●',
  running: '▶',
  thinking: '◌',
  hitl: '⚠',
  error: '✗',
  exited: '○',
}

/** Uppercase tag for color-blind / log-friendly reading. */
const STATUS_TAG: Record<string, string> = {
  idle: 'IDLE',
  /** Agent is executing tools / streaming — not waiting on you (unless another HITL opens). */
  running: 'RUN',
  thinking: 'THINK',
  hitl: 'HITL',
  error: 'ERROR',
  exited: 'EXIT',
}

/** Short hint after the tag (replaces raw enum like ``running``). */
const STATUS_HINT: Record<string, string> = {
  idle: 'ready',
  running: 'agent working',
  thinking: 'thinking',
  hitl: 'needs your input',
  error: 'error',
  exited: 'ended',
}

const STATUS_COLORS = {
  idle: 'green',
  running: 'yellow',
  thinking: 'magenta',
  hitl: 'yellow',
  error: 'red',
  exited: 'gray',
} as const

type StatusBadgeColor = (typeof STATUS_COLORS)[keyof typeof STATUS_COLORS]

interface Props {
  thread: string
  /**
   * Same contract as ``Header``: when the layout is split, pass the **main column** width so the
   * bar matches the chat column instead of the full terminal width.
   */
  layoutWidth?: number
}

export const StatusBar = ({ thread, layoutWidth }: Props): React.ReactElement => {
  const status = useSessionStore((s) => s.status)
  const budgetUi = useSessionStore((s) => s.budgetUi)
  const sessionId = useSessionStore((s) => s.sessionId)
  const { columns } = useWindowSize()
  /** ``layoutWidth`` overrides ``useWindowSize().columns`` when the UI is split (see props JSDoc). */
  const termWidth = layoutWidth ?? columns ?? 80

  const icon = STATUS_LABEL[status] ?? '●'
  const tag = STATUS_TAG[status] ?? status.toUpperCase()
  let color: StatusBadgeColor | 'white' =
    status in STATUS_COLORS ? STATUS_COLORS[status as keyof typeof STATUS_COLORS] : 'white'
  if (budgetUi === 'exhausted') color = 'red'
  else if (budgetUi === 'approaching') color = 'yellow'

  const sessionLabel = sessionId ?? '…'
  const threadLabel = thread || '…'
  const toolNames = useSessionStore((s) => s.toolNames)
  const toolsHint =
    toolNames && toolNames.length > 0 ? `tools:${toolNames.length}` : null
  const totalIn = useSessionStore((s) => s.totalInputTokens)
  const totalOut = useSessionStore((s) => s.totalOutputTokens)
  const totalCost = useSessionStore((s) => s.totalCostUsd)
  const modelName = useSessionStore((s) => s.model)
  const openedAt = useSessionStore((s) => s.sessionOpenedAtMs)
  const nowMs = useSessionStore((s) => s.wallClockMs)
  const uptimeSec =
    openedAt != null ? (Math.max(0, nowMs - openedAt) / 1000).toFixed(1) : null

  return (
    <Box flexDirection="column" width={termWidth} flexShrink={0}>
      <Box
        width={termWidth}
        paddingX={1}
        borderStyle="single"
        borderTop={true}
        borderBottom={false}
        borderLeft={false}
        borderRight={false}
        flexDirection="row"
        flexWrap="wrap"
      >
        <Text color={color} bold>
          {icon} {tag}
        </Text>
        <Text color="gray" dimColor>
          {' · '}
          {STATUS_HINT[status] ?? status}
        </Text>
        <Text color="gray" dimColor>
          {' · '}
          thread:{threadLabel}
        </Text>
        {sessionId ? (
          <Text color="gray" dimColor>
            {' · '}
            session:{sessionLabel}
          </Text>
        ) : null}
        {toolsHint ? (
          <Text color="gray" dimColor>
            {' · '}
            {toolsHint}
          </Text>
        ) : null}
        {(totalIn > 0 || totalOut > 0) && (
          <Text color="gray" dimColor>
            {' · '}
            ↑{totalIn} ↓{totalOut}
          </Text>
        )}
        {totalCost > 1e-12 && (
          <Text color="gray" dimColor>
            {' · '}
            {totalCost < 0.0001 ? `$${totalCost.toFixed(6)}` : `$${totalCost.toFixed(4)}`}
          </Text>
        )}
        {uptimeSec != null && (
          <Text color="gray" dimColor>
            {' · '}
            {uptimeSec}s
          </Text>
        )}
        {modelName ? (
          <Text color="gray" dimColor>
            {' · '}
            model={modelName}
          </Text>
        ) : null}
      </Box>
      {budgetUi !== 'ok' && (
        <Box paddingX={1} width={termWidth} flexDirection="column">
          <StatusMessage variant={budgetUi === 'exhausted' ? 'error' : 'warning'}>
            {budgetUi === 'exhausted'
              ? 'Token budget exhausted — use /budget raise if the runtime allows it'
              : 'Token budget almost exhausted — consider /budget raise'}
          </StatusMessage>
          <Box width={Math.max(8, termWidth - 2)} marginTop={0}>
            <ProgressBar value={budgetUi === 'exhausted' ? 100 : 85} />
          </Box>
        </Box>
      )}
      <Box paddingX={1} width={termWidth}>
        <Text color="gray" dimColor>
          Ctrl+C exit · Ctrl+X cancel · /budget raise
        </Text>
      </Box>
    </Box>
  )
}
