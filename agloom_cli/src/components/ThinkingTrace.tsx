/** Inline reasoning trace — dim text above the assistant reply (OpenCode-style, not collapsible). */

import React from 'react'
import { Box, Text } from 'ink'
import type { ThinkingStep } from '../store/session.js'
import { useSessionStore } from '../store/session.js'
import { wrapTextLines } from '../utils/wrapLines.js'

interface Props {
  steps: ThinkingStep[]
}

export const ThinkingTrace = ({ steps }: Props): React.ReactElement | null => {
  if (steps.length === 0) return null

  const mainColumnWidth = useSessionStore((s) => s.mainColumnWidth)
  const detailCols = Math.max(40, mainColumnWidth - 4)

  return (
    <Box flexDirection="column" marginLeft={2} marginTop={0} marginBottom={0}>
      <Text color="gray" dimColor bold>
        Reasoning
      </Text>
      {steps.map((s) => {
        const head = s.label ?? s.step
        const timing = s.elapsedMs != null ? ` · ${s.elapsedMs}ms` : ''
        const detailRows = s.detail ? wrapTextLines(s.detail, detailCols) : []
        return (
          <Box key={s.id} flexDirection="column">
            <Text color="gray" dimColor wrap="wrap">
              {head}
              {timing}
            </Text>
            {detailRows.map((row, i) => (
              <Text key={`${s.id}-d-${i}`} color="gray" dimColor wrap="wrap">
                {row}
              </Text>
            ))}
          </Box>
        )
      })}
    </Box>
  )
}
