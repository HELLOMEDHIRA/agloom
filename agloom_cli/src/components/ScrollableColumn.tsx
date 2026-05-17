/** Fixed-height column with line-based scroll (Ctrl+[ / Ctrl+] or PgUp/PgDn). */

import React, { useEffect, useMemo, useState } from 'react'
import { Box, Text, useInput } from 'ink'

interface Props {
  /** Max visible content lines (excluding optional scroll hint). */
  maxLines: number
  lines: React.ReactElement[]
  /** When true, new lines keep the viewport pinned to the bottom only if the user was already at the bottom. */
  pinToBottomOnGrow?: boolean
  showScrollHint?: boolean
  /** When false, only PgUp/PgDn scroll (avoids duplicate Ctrl+[/] handlers in split layout). */
  allowBracketScroll?: boolean
}

export const ScrollableColumn = ({
  maxLines,
  lines,
  pinToBottomOnGrow = true,
  showScrollHint = true,
  allowBracketScroll = true,
}: Props): React.ReactElement => {
  const total = lines.length
  const maxScroll = Math.max(0, total - maxLines)
  const [scrollTop, setScrollTop] = useState(maxScroll)
  /** When false, user has scrolled up — do not snap to bottom on token/line growth. */
  const [stickToBottom, setStickToBottom] = useState(true)

  useEffect(() => {
    setScrollTop((prev) => {
      if (pinToBottomOnGrow && stickToBottom) return maxScroll
      return Math.min(prev, maxScroll)
    })
  }, [maxScroll, pinToBottomOnGrow, stickToBottom, total])

  useInput((_char, key) => {
    if (total <= maxLines) return
    const step = key.pageUp || key.pageDown ? Math.max(3, maxLines - 1) : 1
    if (key.pageDown || (allowBracketScroll && key.ctrl && _char === ']')) {
      setScrollTop((s) => {
        const next = Math.min(maxScroll, s + step)
        setStickToBottom(next >= maxScroll)
        return next
      })
      return
    }
    if (key.pageUp || (allowBracketScroll && key.ctrl && _char === '[')) {
      setStickToBottom(false)
      setScrollTop((s) => Math.max(0, s - step))
    }
  })

  const visible = useMemo(
    () => lines.slice(scrollTop, scrollTop + maxLines),
    [lines, maxLines, scrollTop],
  )

  const canScroll = total > maxLines

  return (
    <Box flexDirection="column" flexGrow={1} minHeight={0}>
      <Box flexDirection="column" flexGrow={1} minHeight={0} overflow="hidden">
        {visible.length > 0 ? (
          visible.map((line, i) => (
            <Box key={`${scrollTop + i}-${i}`} flexShrink={0}>
              {line}
            </Box>
          ))
        ) : (
          <Text color="gray" dimColor>
            {' '}
          </Text>
        )}
      </Box>
      {showScrollHint && canScroll && (
        <Text color="gray" dimColor wrap="truncate-end">
          {scrollTop > 0 ? '▲' : ' '} {scrollTop < maxScroll ? '▼' : ' '}
          {' '}
          rows {scrollTop + 1}-{Math.min(scrollTop + maxLines, total)}/{total}
          {' · '}
          Ctrl+[/] scroll
        </Text>
      )}
    </Box>
  )
}
