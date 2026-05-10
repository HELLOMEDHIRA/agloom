/**
 * Header — top bar showing runtime version, model, pattern, and token count.
 * Renders once on mount and whenever metadata changes (low re-render frequency).
 */

import React from 'react'
import { Box, Text, useWindowSize } from 'ink'
import { useSessionStore } from '../store/session.js'
import { fmtTokens } from '../utils/format.js'

interface HeaderProps {
  /** When set (e.g. split layout with metrics sidebar), overrides terminal width. */
  layoutWidth?: number
}

export function Header({ layoutWidth }: HeaderProps): React.ReactElement {
  const runtimeVersion = useSessionStore((s) => s.runtimeVersion)
  const model = useSessionStore((s) => s.model)
  const totalIn = useSessionStore((s) => s.totalInputTokens)
  const totalOut = useSessionStore((s) => s.totalOutputTokens)
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const pattern = activeTurn?.pattern
  const { columns } = useWindowSize()
  const termWidth = layoutWidth ?? columns ?? 80
  const tokenStr = totalIn + totalOut > 0 ? `${fmtTokens(totalIn)}↑ ${fmtTokens(totalOut)}↓` : ''

  return (
    <Box
      width={termWidth}
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
      {model && (
        <Box marginRight={1}>
          <Text color="blue" dimColor>
            [{model}]
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
