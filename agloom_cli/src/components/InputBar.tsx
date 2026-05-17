/** Composer: multiline when `pendingLines`; paste/newlines handled in `App` via `onChange`. Uses `ink-text-input` (controlled); `@inkjs/ui` TextInput is uncontrolled. */

import React, { useEffect, useRef, useState } from 'react'
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
  /** Ctrl+Y / hide or show dim reasoning trace — runs even while the agent is busy. */
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
  const showHistorySuggestions =
    !isDisabled && suggestions !== undefined && suggestions.length > 0 && !value.startsWith('/')

  const [selectedSuggestion, setSelectedSuggestion] = useState(0)
  const pendingSuggestionRef = useRef<string | null>(null)
  const suggestionKey = suggestions?.join('\u0000') ?? ''

  useEffect(() => {
    setSelectedSuggestion(0)
  }, [suggestionKey])

  const applySuggestion = (text: string): void => {
    pendingSuggestionRef.current = text
    onChange(text)
  }

  const handleComposerChange = (v: string): void => {
    const pending = pendingSuggestionRef.current
    if (pending !== null) {
      if (v === pending) {
        pendingSuggestionRef.current = null
        return
      }
      pendingSuggestionRef.current = null
    }
    onChange(v)
  }

  useInput((_input, key) => {
    if (isCtrlY(_input, key)) {
      onThinkingHotkey?.()
      return
    }
    if (isDisabled) return

    if (showHistorySuggestions && suggestions) {
      if (key.upArrow) {
        setSelectedSuggestion((i) => (i - 1 + suggestions.length) % suggestions.length)
        return
      }
      if (key.downArrow) {
        setSelectedSuggestion((i) => (i + 1) % suggestions.length)
        return
      }
      if (key.tab) {
        const pick = suggestions[selectedSuggestion] ?? suggestions[0]
        if (pick) applySuggestion(pick)
        return
      }
    }

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

      {showHistorySuggestions && suggestions && (
        <Box flexDirection="column" marginX={2} marginBottom={0}>
          {suggestions.map((s, i) => {
            const picked = i === selectedSuggestion
            const label = s.length > 140 ? `${s.slice(0, 137)}…` : s
            return (
              <Text key={`${i}-${s.slice(0, 40)}`} wrap="truncate-end">
                <Text color={picked ? accent : 'gray'} bold={picked} dimColor={!picked}>
                  {picked ? '▸ ' : '  '}
                  {label}
                </Text>
              </Text>
            )
          })}
          <Text color="gray" dimColor>
            ↑↓ select · Tab apply · Ctrl+P/N full history
          </Text>
        </Box>
      )}

      {ml && pendingLines.length > 0 && (
        <Box flexDirection="column" marginX={2} marginBottom={0}>
          {pendingLines.map((ln, i) => (
            <Text key={`${i}-${ln.slice(0, 24)}`} dimColor>
              {ln.length > 160 ? `${ln.slice(0, 157)}…` : ln}
            </Text>
          ))}
          <Text dimColor>── blank line + Enter sends · Ctrl+P/N history · Ctrl+Y or /think reasoning</Text>
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
            onChange={handleComposerChange}
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
