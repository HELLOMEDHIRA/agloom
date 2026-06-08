/** Scrollable completed-turn history (left chat pane). */

import React, { useMemo } from 'react'
import { Box } from 'ink'
import type { CompletedTurn } from '../store/session.js'
import { useSessionStore } from '../store/session.js'
import { ScrollableColumn } from './ScrollableColumn.js'
import { flattenCompletedTurnLines } from './transcriptLines.js'

interface Props {
  turns: CompletedTurn[]
  width: number
  maxLines: number
  /** When false, chat scroll uses PgUp/PgDn only (sidebar owns Ctrl+[/] in split layout). */
  allowBracketScroll?: boolean
  scrollActive?: boolean
  focusHint?: string
}

export const ChatTranscript = ({
  turns,
  width,
  maxLines,
  allowBracketScroll = true,
  scrollActive = true,
  focusHint,
}: Props): React.ReactElement => {
  const toolNames = useSessionStore((s) => s.toolNames)

  const lines = useMemo(() => {
    const out: React.ReactElement[] = []
    for (const turn of turns) {
      out.push(...flattenCompletedTurnLines(turn, { width, toolNames }))
    }
    return out
  }, [turns, width, toolNames])

  return (
    <Box flexGrow={1} minHeight={0} flexDirection="column">
      <ScrollableColumn
        maxLines={maxLines}
        lines={lines}
        pinToBottomOnGrow
        allowBracketScroll={allowBracketScroll}
        scrollActive={scrollActive}
        focusHint={focusHint}
      />
    </Box>
  )
}
