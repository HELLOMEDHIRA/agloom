/** CompletedTurnCard — renders a finished conversation turn in the live Ink tree (replay-safe). */

import React, { memo } from 'react'
import { Box, Text } from 'ink'
import type { CompletedTurn } from '../store/session.js'
import { effectiveToolCallExpanded, useSessionStore } from '../store/session.js'
import { ToolCallLine } from './ToolCallLine.js'
import { WorkerLine } from './WorkerLine.js'
import { renderMarkdown } from '../utils/format.js'

interface Props {
  turn: CompletedTurn
}

const CompletedTurnCardInner = ({ turn }: Props): React.ReactElement => {
  const expandHistoryThinking = useSessionStore((s) => s.expandHistoryThinking)
  const termWidth = process.stdout.columns ?? 80
  const mdResponse = renderMarkdown(turn.assistantMessage, termWidth - 4)
  const nThink = turn.thinkingSteps.length

  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text bold color="cyan">
          ❯{' '}
        </Text>
        <Text bold>{turn.userMessage}</Text>
      </Box>

      {nThink > 0 && !expandHistoryThinking && (
        <Box marginLeft={2} marginTop={0}>
          <Text color="gray" dimColor>
            ▸ Thought · {nThink} step{nThink === 1 ? '' : 's'} (Ctrl+Y expand)
          </Text>
        </Box>
      )}

      {nThink > 0 && expandHistoryThinking && (
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
          {turn.pattern && (
            <Text color="magenta" dimColor>
              ▸ {turn.pattern}
            </Text>
          )}
          {turn.thinkingSteps.map((s) => (
            <Box key={s.id} flexDirection="column">
              <Text color="gray" dimColor>
                ▸ {s.label ?? s.step}
                {s.elapsedMs != null ? ` · ${s.elapsedMs}ms` : ''}
              </Text>
              {s.detail ? (
                <Text color="gray" dimColor wrap="truncate-end">
                  {s.detail}
                </Text>
              ) : null}
            </Box>
          ))}
        </Box>
      )}

      {turn.workers.length > 0 && (
        <Box flexDirection="column">
          {turn.workers.map((w) => (
            <WorkerLine key={w.id} worker={w} />
          ))}
        </Box>
      )}

      {turn.toolCalls.length > 0 && (
        <Box flexDirection="column">
          {turn.toolCalls.map((tc) => (
            <ToolCallLine key={tc.id} tc={tc} expanded={effectiveToolCallExpanded(tc, {})} />
          ))}
        </Box>
      )}

      <Box marginLeft={2} marginTop={0} flexDirection="column">
        {mdResponse.split('\n').map((line, i) => (
          <Text key={i}>{line}</Text>
        ))}
      </Box>

      {(turn.tokens !== undefined || turn.pattern) && (
        <Box marginLeft={2}>
          <Text color="gray" dimColor>
            {[turn.pattern, turn.tokens !== undefined ? `${turn.tokens} tok` : '']
              .filter(Boolean)
              .join(' · ')}
          </Text>
        </Box>
      )}

      <Box>
        <Text color="gray" dimColor>
          {'─'.repeat(Math.min(termWidth - 2, 60))}
        </Text>
      </Box>
    </Box>
  )
}

export const CompletedTurnCard = memo(CompletedTurnCardInner)
