/**
 * ActiveTurn — the currently in-flight conversation turn.
 *
 * This is the only component that re-renders on every token delta, so it must
 * be kept lean. Completed items (thinking steps, tool calls) are shown concisely;
 * the streaming partial response occupies the bottom of this box.
 */

import React from 'react'
import { Box, Text } from 'ink'
import { useSessionStore } from '../store/session.js'
import { ToolCallLine } from './ToolCallLine.js'
import { WorkerLine } from './WorkerLine.js'
import { useSpinner } from '../hooks/useSpinner.js'
import { truncate } from '../utils/format.js'

export function ActiveTurn(): React.ReactElement | null {
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const status = useSessionStore((s) => s.status)
  const spinner = useSpinner()

  if (!activeTurn) return null

  const isStreaming = status === 'running' || status === 'thinking'
  const { thinkingSteps, toolCalls, workers, streamedTokens, pattern, userMessage } = activeTurn

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* ── User message (echo) ── */}
      <Box>
        <Text bold color="cyan">
          ❯{' '}
        </Text>
        <Text bold>{userMessage}</Text>
      </Box>

      {/* ── Pattern badge ── */}
      {pattern && (
        <Box marginLeft={2}>
          <Text color="magenta">▸ {pattern}</Text>
        </Box>
      )}

      {/* ── Thinking steps (live) ── */}
      {thinkingSteps.map((s) => (
        <Box key={s.id} marginLeft={2}>
          <Text color="gray">▸ {truncate(s.label ?? s.step, 60)}</Text>
        </Box>
      ))}

      {/* ── Workers (live) ── */}
      {workers.map((w) => (
        <WorkerLine key={w.id} worker={w} />
      ))}

      {/* ── Tool calls (live — show result inline) ── */}
      {toolCalls.map((tc) => (
        <ToolCallLine key={tc.id} tc={tc} showResult={true} />
      ))}

      {/* ── Streaming tokens ── */}
      {streamedTokens && (
        <Box marginLeft={2} flexDirection="column">
          {streamedTokens.split('\n').slice(-20).map((line, i) => (
            <Text key={i}>{line}</Text>
          ))}
        </Box>
      )}

      {/* ── Spinner when no tokens yet ── */}
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
