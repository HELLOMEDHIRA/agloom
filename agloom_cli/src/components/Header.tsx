/** Header — top bar showing runtime version, model, pattern, and token count.
 * Renders once on mount and whenever metadata changes (low re-render frequency).
 */

import React from 'react'
import { Box, Text, useWindowSize } from 'ink'
import { useSessionStore } from '../store/session.js'
import { fmtTokens, truncate } from '../utils/format.js'

interface HeaderProps {
  /**
   * Main-column width when the UI is split (e.g. chat + metrics sidebar).
   * **Precedence:** `layoutWidth` wins over {@link useWindowSize}.`columns` so the header
   * wraps/truncates to the chat column, not the full physical terminal.
   */
  layoutWidth?: number
}

export const Header = ({ layoutWidth }: HeaderProps): React.ReactElement => {
  const runtimeVersion = useSessionStore((s) => s.runtimeVersion)
  const model = useSessionStore((s) => s.model)
  const totalIn = useSessionStore((s) => s.totalInputTokens)
  const totalOut = useSessionStore((s) => s.totalOutputTokens)
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const pattern = activeTurn?.pattern
  const { columns } = useWindowSize()
  /** Explicit split-layout width overrides raw terminal columns (see `HeaderProps.layoutWidth`). */
  const termWidth = layoutWidth ?? columns ?? 80
  const tokenStr = totalIn + totalOut > 0 ? `${fmtTokens(totalIn)}↑ ${fmtTokens(totalOut)}↓` : ''
  /** Keep the bar on one row: long ``provider:model`` ids must not wrap over the chat / sidebar. */
  const modelBudget = Math.max(12, termWidth - (tokenStr ? 34 : 22) - (pattern ? String(pattern).length + 4 : 0))
  const modelLabel = model ? truncate(model, modelBudget) : ''

  return (
    <Box
      width={termWidth}
      flexShrink={0}
      paddingX={1}
      borderStyle="single"
      borderBottom={true}
      borderTop={false}
      borderLeft={false}
      borderRight={false}
    >
      {/* Brand */}
      <Text bold color="cyan">
        agloom
      </Text>
      {runtimeVersion && (
        <Text color="gray"> v{runtimeVersion}</Text>
      )}

      <Text> </Text>

      {/* Model badge */}
      {modelLabel && (
        <Box marginRight={1}>
          <Text color="blue" dimColor>
            [{modelLabel}]
          </Text>
        </Box>
      )}

      {/* Pattern badge */}
      {pattern && (
        <Box marginRight={1}>
          <Text color="magenta" dimColor>
            {pattern}
          </Text>
        </Box>
      )}

      {/* Spacer */}
      <Box flexGrow={1} />

      {/* Token counter */}
      {tokenStr && (
        <Text color="gray" dimColor>
          {tokenStr}
        </Text>
      )}
    </Box>
  )
}
