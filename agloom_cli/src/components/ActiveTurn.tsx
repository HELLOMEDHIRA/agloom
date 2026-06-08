/** In-flight turn (streaming, tools, workers). */
import React, { useMemo } from 'react'
import { Box, Text } from 'ink'
import { Badge, Spinner } from '@inkjs/ui'
import { useSessionStore } from '../store/session.js'
import { ThinkingTrace } from './ThinkingTrace.js'
import { ToolCallLine } from './ToolCallLine.js'
import { WorkerLine } from './WorkerLine.js'
import { stripStrayToolJsonFromStream } from '../utils/strayToolJson.js'

export const ActiveTurn = (): React.ReactElement | null => {
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const status = useSessionStore((s) => s.status)
  const toolNames = useSessionStore((s) => s.toolNames)
  const streamedReasoning = activeTurn?.streamedReasoning ?? ''
  const streamedTokens = activeTurn?.streamedTokens ?? ''
  const displayStream = useMemo(() => {
    const allowed = new Set((toolNames ?? []).map((n) => n.trim()).filter(Boolean))
    return stripStrayToolJsonFromStream(streamedTokens, allowed, { permissive: allowed.size === 0 })
  }, [streamedTokens, toolNames])

  if (!activeTurn) return null

  const isStreaming = status === 'running' || status === 'thinking'
  const { thinkingSteps, toolCalls, workers, pattern, userMessage } = activeTurn

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

      {streamedReasoning ? (
        <Box marginLeft={2} flexDirection="column">
          <Text color="magenta" dimColor bold>
            Reasoning
          </Text>
          <Text color="magenta" dimColor wrap="wrap">
            {streamedReasoning}
          </Text>
        </Box>
      ) : null}

      <ThinkingTrace steps={thinkingSteps} />

      {workers.map((w) => (
        <WorkerLine key={w.id} worker={w} />
      ))}

      {toolCalls.map((tc) => (
        <ToolCallLine key={tc.id} tc={tc} />
      ))}

      {displayStream && (
        <Box marginLeft={2} marginTop={1} flexDirection="column">
          {displayStream.split('\n').map((line, i) => (
            <Text key={i} wrap="wrap">
              {line}
            </Text>
          ))}
        </Box>
      )}

      {isStreaming && !displayStream && (
        <Box marginLeft={2}>
          <Spinner label={status === 'thinking' ? 'thinking…' : 'working…'} />
        </Box>
      )}
    </Box>
  )
}
