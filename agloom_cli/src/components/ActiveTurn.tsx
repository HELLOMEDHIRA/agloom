/** In-flight turn (streaming, tools, workers). */
import React from 'react'
import { Box, Text } from 'ink'
import { useSessionStore, effectiveToolCallExpanded } from '../store/session.js'
import { ToolCallLine } from './ToolCallLine.js'
import { WorkerLine } from './WorkerLine.js'
import { useSpinner } from '../hooks/useSpinner.js'
import { truncate } from '../utils/format.js'

export const ActiveTurn = (): React.ReactElement | null => {
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const status = useSessionStore((s) => s.status)
  const expandedMap = useSessionStore((s) => s.toolCallExpandedById)
  const expandActiveThinking = useSessionStore((s) => s.expandActiveThinking)
  const spinner = useSpinner()

  if (!activeTurn) return null

  const isStreaming = status === 'running' || status === 'thinking'
  const { thinkingSteps, toolCalls, workers, streamedTokens, pattern, userMessage } = activeTurn

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text bold color="cyan">
          ❯{' '}
        </Text>
        <Text bold>{userMessage}</Text>
      </Box>

      {pattern && (
        <Box marginLeft={2}>
          <Text color="magenta">▸ {pattern}</Text>
        </Box>
      )}

      {thinkingSteps.length > 0 && expandActiveThinking && (
        <Box
          flexDirection="column"
          marginLeft={2}
          marginTop={0}
          borderStyle="round"
          borderColor="gray"
          paddingX={1}
        >
          <Text bold dimColor color="magenta">
            Thinking
          </Text>
          {thinkingSteps.map((s) => (
            <Box key={s.id} flexDirection="column">
              <Text color="gray">▸ {truncate(s.label ?? s.step, Math.max(40, (process.stdout.columns ?? 80) - 14))}</Text>
              {s.detail ? (
                <Text color="gray" dimColor wrap="truncate-end">
                  {truncate(s.detail, (process.stdout.columns ?? 80) * 2)}
                </Text>
              ) : null}
            </Box>
          ))}
          <Text dimColor color="gray">
            Ctrl+Y or /think — collapse
          </Text>
        </Box>
      )}

      {thinkingSteps.length > 0 && !expandActiveThinking && (
        <Box marginLeft={2} marginTop={0} flexDirection="column">
          <Text color="gray" dimColor>
            ▸ {truncate(thinkingSteps.at(-1)?.label ?? thinkingSteps.at(-1)?.step ?? '…', Math.max(36, (process.stdout.columns ?? 80) - 28))}
            {' · '}
            step {thinkingSteps.length}
            {' · '}
            Ctrl+Y or /think expand
          </Text>
        </Box>
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
        <Box marginLeft={2} flexDirection="column">
          {streamedTokens.split('\n').slice(-20).map((line, i) => (
            <Text key={i}>{line}</Text>
          ))}
        </Box>
      )}

      {isStreaming && !streamedTokens && (
        <Box marginLeft={2}>
          <Text color="cyan">{spinner} </Text>
          <Text color="gray" dimColor>
            {status === 'thinking' ? 'thinking…' : 'working…'}
          </Text>
        </Box>
      )}
    </Box>
  )
}
