/** InputBar — primary message input (optional multiline compose buffer shown above).
 * **Paste with newlines (B1):** when not in explicit multiline mode, `App` passes `onChange` through `splitPastedMultilineWhenSingleLineMode` so bracketed paste opens the same queued-line + blank-Enter send flow (no `onPaste` here — the text input surfaces pastes as a single `onChange` with `\n` embedded).
 * Composer uses **`ink-text-input`** (controlled `value`); `@inkjs/ui` ``TextInput`` is uncontrolled (`defaultValue` only) and is not a drop-in.
 */

import React from 'react'
import { Box, Text } from 'ink'
import { Alert } from '@inkjs/ui'
import TextInput from 'ink-text-input'
import { useInput } from 'ink'
import { useSessionStore } from '../store/session.js'
import { SLASH_HINTS } from '../utils/slashCommands.js'
import { useAgloomTheme } from '../themeContext.js'
import { isCtrlY } from '../utils/keys.js'

interface Props {
  value: string
  onChange: (v: string) => void
  /** Called with current single-line value when user presses Enter. */
  onSubmit: (v: string) => void
  /** When set, rendered above the field as queued lines (multiline compose). */
  pendingLines?: string[]
  onRecallPrev?: () => void
  onRecallNext?: () => void
  /** Fuzzy matches from prompt history (non-slash input). */
  suggestions?: string[]
  /** Match main column width so the composer spans the chat pane. */
  composerWidth?: number
  /** Ctrl+Y / expand thinking — runs even while the agent is busy (composer is disabled). */
  onThinkingHotkey?: () => void
}

export const InputBar = ({
  value,
  onChange,
  onSubmit,
  pendingLines,
  onRecallPrev,
  onRecallNext,
  suggestions,
  composerWidth,
  onThinkingHotkey,
}: Props): React.ReactElement => {
  const theme = useAgloomTheme()
  const accent = theme === 'light' ? 'blue' : 'cyan'
  const status = useSessionStore((s) => s.status)
  const isDisabled = status === 'running' || status === 'thinking' || status === 'hitl'
  const errorMessage = useSessionStore((s) => s.errorMessage)

  const showSlashHints = value.startsWith('/') && value.length >= 1 && !value.includes(' ')

  useInput((_input, key) => {
    if (isCtrlY(_input, key)) {
      onThinkingHotkey?.()
      return
    }
    if (isDisabled) return
    if (key.ctrl && _input === 'p') {
      onRecallPrev?.()
      return
    }
    if (key.ctrl && _input === 'n') {
      onRecallNext?.()
      return
    }
  })

  const ml = pendingLines !== undefined

  return (
    <Box flexDirection="column" width={composerWidth}>
      {errorMessage && status !== 'error' && (
        <Box marginX={1} marginBottom={0}>
          <Alert variant="error" title="Error">
            {errorMessage}
          </Alert>
        </Box>
      )}

      {showSlashHints && (
        <Box flexDirection="column" marginX={2} marginBottom={0}>
          {Object.entries(SLASH_HINTS)
            .filter(([cmd]) => cmd.startsWith(value))
            .slice(0, 6)
            .map(([cmd, hint]) => (
              <Box key={cmd}>
                <Text bold color={accent}>
                  {cmd.padEnd(14)}
                </Text>
                <Text color="gray" dimColor>
                  {hint}
                </Text>
              </Box>
            ))}
        </Box>
      )}

      {suggestions !== undefined && suggestions.length > 0 && !value.startsWith('/') && (
        <Box flexDirection="column" marginX={2} marginBottom={0}>
          {suggestions.map((s, i) => (
            <Text key={`${i}-${s.slice(0, 40)}`} dimColor color="gray">
              ↪ {s.length > 140 ? `${s.slice(0, 137)}…` : s}
            </Text>
          ))}
        </Box>
      )}

      {ml && pendingLines.length > 0 && (
        <Box flexDirection="column" marginX={2} marginBottom={0}>
          {pendingLines.map((ln, i) => (
            <Text key={`${i}-${ln.slice(0, 24)}`} dimColor>
              {ln.length > 160 ? `${ln.slice(0, 157)}…` : ln}
            </Text>
          ))}
          <Text dimColor>── blank line + Enter sends · Ctrl+P/N history · Ctrl+Y or /think thinking</Text>
        </Box>
      )}

      <Box paddingX={1} flexDirection="row" width={composerWidth}>
        <Text bold color={isDisabled ? 'gray' : accent}>
          {'❯ '}
        </Text>
        <Box flexGrow={1} minWidth={8}>
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
            placeholder={
              ml
                ? 'Line… Enter adds · blank Enter sends · /help'
                : 'Message agloom…    /help for commands'
            }
          />
        )}
        </Box>
      </Box>
    </Box>
  )
}
