/**
 * StatusBar — bottom bar with session status, thread id, and Ctrl shortcuts.
 */

import React, { useEffect, useState } from 'react'
import { Box, Text, useWindowSize } from 'ink'
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
  running: 'BUSY',
  thinking: 'THINK',
  hitl: 'HITL',
  error: 'ERROR',
  exited: 'EXIT',
}

const STATUS_COLOR: Record<string, string> = {
  idle: 'green',
  running: 'yellow',
  thinking: 'magenta',
  hitl: 'yellow',
  error: 'red',
  exited: 'gray',
}

interface Props {
  thread: string
  layoutWidth?: number
}

export const StatusBar = ({ thread, layoutWidth }: Props): React.ReactElement => {
  const status = useSessionStore((s) => s.status)
  const budgetUi = useSessionStore((s) => s.budgetUi)
  const sessionId = useSessionStore((s) => s.sessionId)
  const { columns } = useWindowSize()
  const termWidth = layoutWidth ?? columns ?? 80

  const icon = STATUS_LABEL[status] ?? '●'
  const tag = STATUS_TAG[status] ?? status.toUpperCase()
  let color = STATUS_COLOR[status] ?? 'white'
  if (budgetUi === 'exhausted') color = 'red'
  else if (budgetUi === 'approaching') color = 'yellow'

  const sessionShort = sessionId ? sessionId.slice(0, 12) : '…'
  const threadShort = thread.slice(0, 12)
  const toolNames = useSessionStore((s) => s.toolNames)
  const toolsHint =
    toolNames && toolNames.length > 0 ? `tools:${toolNames.length}` : null
  const totalIn = useSessionStore((s) => s.totalInputTokens)
  const totalOut = useSessionStore((s) => s.totalOutputTokens)
  const totalCost = useSessionStore((s) => s.totalCostUsd)
  const modelName = useSessionStore((s) => s.model)
  const openedAt = useSessionStore((s) => s.sessionOpenedAtMs)
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    if (openedAt == null) return
    const id = setInterval(() => {
      setNowMs(Date.now())
    }, 1000)
    return () => {
      clearInterval(id)
    }
  }, [openedAt])
  const uptimeSec =
    openedAt != null ? ((nowMs - openedAt) / 1000).toFixed(1) : null

  return (
    <Box
      width={termWidth}
      paddingX={1}
      borderStyle="single"
      borderTop={true}
      borderBottom={false}
      borderLeft={false}
      borderRight={false}
    >
      {/* Status: icon + color + uppercase tag (E2 color-blind aid) */}
      <Text color={color as 'green' | 'yellow' | 'magenta' | 'red' | 'gray' | 'white'} bold>
        {icon}{' '}
        {tag}
      </Text>
      <Text color="gray" dimColor>
        {' '}
        {status}
      </Text>

      <Text color="gray" dimColor>
        {'  ·  '}
      </Text>

      {/* Thread */}
      <Text color="gray" dimColor>
        thread:{threadShort}
      </Text>

      {sessionId && (
        <>
          <Text color="gray" dimColor>
            {'  ·  '}
          </Text>
          <Text color="gray" dimColor>
            session:{sessionShort}
          </Text>
        </>
      )}

      {toolsHint && (
        <>
          <Text color="gray" dimColor>
            {'  ·  '}
          </Text>
          <Text color="gray" dimColor>
            {toolsHint}
          </Text>
        </>
      )}

      {(totalIn > 0 || totalOut > 0) && (
        <>
          <Text color="gray" dimColor>
            {'  ·  '}
          </Text>
          <Text color="gray" dimColor>
            ↑{totalIn} ↓{totalOut}
          </Text>
        </>
      )}

      {totalCost > 0 && (
        <>
          <Text color="gray" dimColor>
            {'  ·  '}
          </Text>
          <Text color="gray" dimColor>
            ${totalCost.toFixed(4)}
          </Text>
        </>
      )}

      {uptimeSec != null && (
        <>
          <Text color="gray" dimColor>
            {'  ·  '}
          </Text>
          <Text color="gray" dimColor>
            {uptimeSec}s
          </Text>
        </>
      )}

      {modelName && (
        <>
          <Text color="gray" dimColor>
            {'  ·  '}
          </Text>
          <Text color="gray" dimColor>
            model={modelName.length > 24 ? `${modelName.slice(0, 24)}…` : modelName}
          </Text>
        </>
      )}

      <Box flexGrow={1} />

      {/* Keyboard hints */}
      <Text color="gray" dimColor>
        Ctrl+C exit  Ctrl+X cancel  Ctrl+T / t tools  /budget raise
      </Text>
    </Box>
  )
}
