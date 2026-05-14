/** CompletedTurnCard — renders a finished conversation turn.
 * This component is always used inside a terminal `<Static>` wrapper: it is written to the screen once and not live-updated. Keep it pure / side-effect free. Do NOT use hooks that cause re-renders (timers, subscriptions, etc.).
 */

import React from 'react'
import { Box, Text } from 'ink'
import type { CompletedTurn } from '../store/session.js'
import { effectiveToolCallExpanded } from '../store/session.js'
import { ToolCallLine } from './ToolCallLine.js'
import { WorkerLine } from './WorkerLine.js'
import { renderMarkdown } from '../utils/format.js'

interface Props {
  turn: CompletedTurn
}

export const CompletedTurnCard = ({ turn }: Props): React.ReactElement => {
  // <Static> renders outside the live tree; read terminal width directly.
  const termWidth = process.stdout.columns ?? 80
  const mdResponse = renderMarkdown(turn.assistantMessage, termWidth - 4)

  return (
    <Box flexDirection="column" marginBottom={1}>
      {/* ── User message ── */}
      <Box>
        <Text bold color="cyan">
          ❯{' '}
        </Text>
        <Text bold>{turn.userMessage}</Text>
      </Box>

      {/* ── Pattern + thinking steps (collapsed to first 3) ── */}
      {turn.thinkingSteps.length > 0 && (
        <Box flexDirection="column" marginLeft={2} marginTop={0}>
          {turn.pattern && (
            <Text color="magenta" dimColor>
              ▸ {turn.pattern}
            </Text>
          )}
          {turn.thinkingSteps.slice(0, 3).map((s) => (
            <Text key={s.id} color="gray" dimColor>
              ▸ {s.label ?? s.step}
            </Text>
          ))}
          {turn.thinkingSteps.length > 3 && (
            <Text color="gray" dimColor>
              ▸ +{turn.thinkingSteps.length - 3} more steps
            </Text>
          )}
        </Box>
      )}

      {/* ── Workers ── */}
      {turn.workers.length > 0 && (
        <Box flexDirection="column">
          {turn.workers.map((w) => (
            <WorkerLine key={w.id} worker={w} />
          ))}
        </Box>
      )}

      {/* ── Tool calls ── */}
      {turn.toolCalls.length > 0 && (
        <Box flexDirection="column">
          {turn.toolCalls.map((tc) => (
            <ToolCallLine key={tc.id} tc={tc} expanded={effectiveToolCallExpanded(tc, {})} />
          ))}
        </Box>
      )}

      {/* ── Assistant response ── */}
      <Box marginLeft={2} marginTop={0} flexDirection="column">
        {mdResponse.split('\n').map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
      </Box>

      {/* ── Token footer ── */}
      {(turn.tokens !== undefined || turn.pattern) && (
        <Box marginLeft={2}>
          <Text color="gray" dimColor>
            {[turn.pattern, turn.tokens !== undefined ? `${turn.tokens} tok` : '']
              .filter(Boolean)
              .join(' · ')}
          </Text>
        </Box>
      )}

      {/* Divider */}
      <Box>
        <Text color="gray" dimColor>
          {'─'.repeat(Math.min(termWidth - 2, 60))}
        </Text>
      </Box>
    </Box>
  )
}
