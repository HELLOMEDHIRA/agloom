/**
 * StatusBar — bottom bar with session status, thread id, and Ctrl shortcuts.
 */

import React from 'react'
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

export function StatusBar({ thread, layoutWidth }: Props): React.ReactElement {
  const status = useSessionStore((s) => s.status)
  const sessionId = useSessionStore((s) => s.sessionId)
  const { columns } = useWindowSize()
  const termWidth = layoutWidth ?? columns ?? 80

  const icon = STATUS_LABEL[status] ?? '●'
  const color = STATUS_COLOR[status] ?? 'white'

  const sessionShort = sessionId ? sessionId.slice(0, 12) : '…'
  const threadShort = thread.slice(0, 12)

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
      {/* Status indicator */}
      <Text color={color as Parameters<typeof Text>[0]['color']} bold>
        {icon} {status}
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

      <Box flexGrow={1} />

      {/* Keyboard hints */}
      <Text color="gray" dimColor>
        Ctrl+C exit  Ctrl+X cancel
      </Text>
    </Box>
  )
}
