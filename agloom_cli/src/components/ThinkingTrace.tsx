/** Inline reasoning trace — dim text above the assistant reply (OpenCode-style, not collapsible). */

import React from 'react'
import { Box, Text } from 'ink'
import type { ThinkingStep } from '../store/session.js'
import { useSessionStore } from '../store/session.js'
import { truncate } from '../utils/format.js'

interface Props {
  steps: ThinkingStep[]
  /** Cap detail width for in-flight turns; completed turns show full detail. */
  maxDetailChars?: number
}

export const ThinkingTrace = ({ steps, maxDetailChars }: Props): React.ReactElement | null => {
  if (steps.length === 0) return null

  const mainColumnWidth = useSessionStore((s) => s.mainColumnWidth)
  const detailCap = maxDetailChars ?? Math.max(120, mainColumnWidth * 3)

  return (
    <Box flexDirection="column" marginLeft={2} marginTop={0} marginBottom={0}>
      {steps.map((s) => {
        const head = s.label ?? s.step
        const timing = s.elapsedMs != null ? ` · ${s.elapsedMs}ms` : ''
        return (
          <Box key={s.id} flexDirection="column">
            <Text color="gray" dimColor>
              {head}
              {timing}
            </Text>
            {s.detail ? (
              <Text color="gray" dimColor wrap="truncate-end">
                {maxDetailChars != null ? truncate(s.detail, detailCap) : s.detail}
              </Text>
            ) : null}
          </Box>
        )
      })}
    </Box>
  )
}
