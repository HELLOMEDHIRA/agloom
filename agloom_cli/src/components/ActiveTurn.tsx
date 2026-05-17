/** In-flight turn (streaming, tools, workers). */
import React from 'react'
import { Box, Text } from 'ink'
import { Badge, Spinner } from '@inkjs/ui'
import { useSessionStore, effectiveToolCallExpanded } from '../store/session.js'
import { ThinkingTrace } from './ThinkingTrace.js'
import { ToolCallLine } from './ToolCallLine.js'
import { WorkerLine } from './WorkerLine.js'

export const ActiveTurn = (): React.ReactElement | null => {
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const status = useSessionStore((s) => s.status)
  const expandedMap = useSessionStore((s) => s.toolCallExpandedById)
  const hideThinkingTrace = useSessionStore((s) => s.hideThinkingTrace)
  const mainColumnWidth = useSessionStore((s) => s.mainColumnWidth)

  if (!activeTurn) return null

  const isStreaming = status === 'running' || status === 'thinking'
  const { thinkingSteps, toolCalls, workers, streamedTokens, pattern, userMessage } = activeTurn

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text bold color="cyan">
          ❯{' '}
        </Text>
        <Text bold wrap="wrap">
          {userMessage}
        </Text>
      </Box>

      {pattern && (
        <Box marginLeft={2}>
          <Badge color="magenta">{pattern}</Badge>
        </Box>
      )}

      {!hideThinkingTrace && (
        <ThinkingTrace steps={thinkingSteps} maxDetailChars={Math.max(120, mainColumnWidth * 2)} />
      )}

      {workers.map((w) => (
        <WorkerLine key={w.id} worker={w} />
      ))}

      {toolCalls.map((tc) => (
        <ToolCallLine
          key={tc.id}
          tc={tc}
          expanded={effectiveToolCallExpanded(tc, expandedMap)}
        />
      ))}

      {streamedTokens && (
        <Box marginLeft={2} marginTop={1} flexDirection="column">
          {streamedTokens.split('\n').slice(-20).map((line, i) => (
            <Text key={i} wrap="wrap">
              {line}
            </Text>
          ))}
        </Box>
      )}

      {isStreaming && !streamedTokens && (
        <Box marginLeft={2}>
          <Spinner label={status === 'thinking' ? 'thinking…' : 'working…'} />
        </Box>
      )}
    </Box>
  )
}
