/**
 * InputBar — the primary message input at the bottom of the screen.
 *
 * Features:
 *  - Disabled (greyed placeholder) while the agent is running / thinking.
 *  - Slash-command prefix: typing '/' activates a hint overlay.
 *  - Ctrl+C / Ctrl+X shortcuts advertised in the hint line.
 */

import React from 'react'
import { Box, Text } from 'ink'
import TextInput from 'ink-text-input'
import { useSessionStore } from '../store/session.js'

interface Props {
  value: string
  onChange: (v: string) => void
  onSubmit: (v: string) => void
}

const SLASH_HINTS: Record<string, string> = {
  '/help': 'show keyboard shortcuts',
  '/cancel': 'cancel current run  (Ctrl+X)',
  '/clear': 'clear conversation',
  '/model': 'show active model',
  '/diag': 'toggle diagnostic log',
  '/stats': 'toggle session metrics sidebar',
  '/feedback': '/feedback <1-5> [comment]',
  '/exit': 'quit',
}

export function InputBar({ value, onChange, onSubmit }: Props): React.ReactElement {
  const status = useSessionStore((s) => s.status)
  const isDisabled = status === 'running' || status === 'thinking' || status === 'hitl'
  const errorMessage = useSessionStore((s) => s.errorMessage)

  const showSlashHints = value.startsWith('/') && value.length >= 1 && !value.includes(' ')

  return (
    <Box flexDirection="column">
      {/* Transient error banner */}
      {errorMessage && status !== 'error' && (
        <Box marginX={1}>
          <Text color="red" dimColor>
            ⚠ {errorMessage}
          </Text>
        </Box>
      )}

      {/* Slash-command hints overlay */}
      {showSlashHints && (
        <Box flexDirection="column" marginX={2} marginBottom={0}>
          {Object.entries(SLASH_HINTS)
            .filter(([cmd]) => cmd.startsWith(value))
            .slice(0, 6)
            .map(([cmd, hint]) => (
              <Box key={cmd}>
                <Text bold color="cyan">
                  {cmd.padEnd(14)}
                </Text>
                <Text color="gray" dimColor>
                  {hint}
                </Text>
              </Box>
            ))}
        </Box>
      )}

      {/* Input row */}
      <Box paddingX={1}>
        <Text bold color={isDisabled ? 'gray' : 'cyan'}>
          {'❯ '}
        </Text>
        {isDisabled ? (
          <Text color="gray" dimColor>
            {status === 'running' || status === 'thinking'
              ? 'running…  Ctrl+X to cancel'
              : '…'}
          </Text>
        ) : (
          <TextInput
            value={value}
            onChange={onChange}
            onSubmit={onSubmit}
            placeholder="Message agloom…    /help for commands"
          />
        )}
      </Box>
    </Box>
  )
}
