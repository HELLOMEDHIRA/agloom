/** Scrollable completed-turn history (left chat pane). */

import React, { useMemo } from 'react'
import { Box } from 'ink'
import type { CompletedTurn } from '../store/session.js'
import { useSessionStore } from '../store/session.js'
import { ScrollableColumn } from './ScrollableColumn.js'
import { flattenCompletedTurnLines } from './transcriptLines.js'

interface Props {
  turns: CompletedTurn[]
  hideThinkingTrace: boolean
  width: number
  maxLines: number
}

export const ChatTranscript = ({
  turns,
  hideThinkingTrace,
  width,
  maxLines,
}: Props): React.ReactElement => {
  const toolCallExpandedById = useSessionStore((s) => s.toolCallExpandedById)

  const lines = useMemo(() => {
    const out: React.ReactElement[] = []
    for (const turn of turns) {
      out.push(...flattenCompletedTurnLines(turn, { hideThinkingTrace, width, toolCallExpandedById }))
    }
    return out
  }, [turns, hideThinkingTrace, width, toolCallExpandedById])

  return (
    <Box flexGrow={1} minHeight={0} flexDirection="column">
      <ScrollableColumn maxLines={maxLines} lines={lines} pinToBottomOnGrow />
    </Box>
  )
}
