/**
 * HITLPrompt — replaces the normal input bar when a HITL gate is pending.
 *
 * Renders beautiful button-style options for tool approvals / clarifications.
 * The model can also ask questions mid-execution via the ask_user meta-tool
 * (kind=clarification) with custom Yes/No/Custom answer buttons.
 */

import React, { useState, useMemo } from 'react'
import { Box, Text, useInput } from 'ink'
import { StatusMessage } from '@inkjs/ui'
import TextInput from 'ink-text-input'
import type { HITLRequest } from '../store/session.js'
import type { AGPBridge } from '../runtime/bridge.js'
import { truncate } from '../utils/format.js'

interface Props {
  request: HITLRequest
  bridge: AGPBridge
}

const BTN_COLORS = ['green', 'red', 'blue', 'yellow', 'cyan', 'magenta'] as const
type BtnColor = (typeof BTN_COLORS)[number]

interface ButtonDef {
  key: string
  label: string
  decision: string
  color: BtnColor
}

const BUTTONS_BY_KIND: Record<string, ButtonDef[]> = {
  tool_approval: [
    { key: 'y', label: 'Accept', decision: 'accept', color: 'green' as BtnColor },
    { key: 'n', label: 'Reject', decision: 'reject', color: 'red' as BtnColor },
    { key: 'a', label: 'Allowlist', decision: 'allowlist', color: 'blue' as BtnColor },
  ],
  pattern_approval: [
    { key: 'y', label: 'Accept', decision: 'accept', color: 'green' as BtnColor },
    { key: 'n', label: 'Reject', decision: 'reject', color: 'red' as BtnColor },
  ],
  worker_approval: [
    { key: 'y', label: 'Accept', decision: 'accept', color: 'green' as BtnColor },
    { key: 'n', label: 'Reject', decision: 'reject', color: 'red' as BtnColor },
    { key: 's', label: 'Skip', decision: 'skip', color: 'yellow' as BtnColor },
  ],
  react_recovery: [
    { key: 'r', label: 'Retry', decision: 'retry', color: 'green' as BtnColor },
    { key: 's', label: 'Stop', decision: 'stop', color: 'red' as BtnColor },
  ],
}

const hitlDefaultDecision = (kind: string, wireDefault?: string): string => {
  if (kind === 'clarification') return wireDefault ?? 'cancelled'
  return wireDefault ?? 'reject'
}

const buildOptionButtons = (options: string[]): ButtonDef[] => {
  const colors: BtnColor[] = ['cyan', 'green', 'yellow', 'magenta', 'blue']
  return options.map((opt, i) => ({
    key: String(i + 1),
    label: opt,
    decision: opt,
    color: colors[i % colors.length]!,
  }))
}

const buildButtons = (kind: string, options: string[]): { buttons: ButtonDef[] } => {
  const predefined = BUTTONS_BY_KIND[kind]
  if (predefined) return { buttons: predefined }
  if (options.length > 0) return { buttons: buildOptionButtons(options) }
  return { buttons: [{ key: 'y', label: 'Accept', decision: 'accept', color: 'green' as BtnColor }, { key: 'n', label: 'Reject', decision: 'reject', color: 'red' as BtnColor }] }
}

export const HITLPrompt = ({ request, bridge }: Props): React.ReactElement => {
  const [freeText, setFreeText] = useState('')
  const [mode, setMode] = useState<'option' | 'free_text'>(
    request.kind === 'clarification' && request.options.length === 0 ? 'free_text' : 'option',
  )

  const { buttons } = useMemo(() => buildButtons(request.kind, request.options), [request.kind, request.options])

  const sendDefault = (): void => {
    bridge.hitlRespond(request.requestId, hitlDefaultDecision(request.kind, request.default))
  }

  useInput((input: string, key) => {
    if (key.escape) {
      if (mode === 'free_text') { setMode('option'); setFreeText(''); return }
      sendDefault()
      return
    }
    if (mode === 'option') {
      if (key.return) { sendDefault(); return }
      if (request.kind === 'clarification' && input.toLowerCase() === 'c') {
        setMode('free_text')
        return
      }
      for (const btn of buttons) {
        if (input.toLowerCase() === btn.key) {
          bridge.hitlRespond(request.requestId, btn.decision)
          return
        }
      }
    }
  })

  // ── Free-text mode (clarifications without options, or user pressed C) ─────
  const hitlSummary = `${request.kind}${request.tool ? ` · ${request.tool}` : ''}`

  if (mode === 'free_text') {
    return (
      <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1} paddingY={0} marginBottom={0}>
        <Box marginBottom={0}>
          <StatusMessage variant="warning">{`HITL · ${hitlSummary}`}</StatusMessage>
        </Box>
        {request.detail && <Box marginLeft={2}><Text color="white">{truncate(request.detail, 300)}</Text></Box>}
        {request.question && <Box marginLeft={2}><Text color="cyan" italic>{request.question}</Text></Box>}
        <Box marginLeft={2}>
          <Text color="gray" dimColor>Type your answer · Enter to submit · Esc to go back</Text>
        </Box>
        <Box marginTop={0}>
          <Text color="yellow" bold>{'  ❯ '}</Text>
          <TextInput value={freeText} onChange={setFreeText} onSubmit={(t) => { const a = t.trim(); if (a) { bridge.hitlRespond(request.requestId, 'answered', a); setFreeText('') } else { sendDefault(); setFreeText('') } }} placeholder="Your answer…" />
        </Box>
      </Box>
    )
  }

  // ── Button mode ──────────────────────────────────────────────────────────
  return (
    <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1} paddingY={0} marginBottom={0}>
      <Box marginBottom={0}>
        <StatusMessage variant="warning">{`HITL · ${hitlSummary}`}</StatusMessage>
      </Box>

      {/* Detail / Question */}
      {request.detail && <Box marginLeft={2} marginTop={1}><Text color="white">{truncate(request.detail, 300)}</Text></Box>}
      {request.question && <Box marginLeft={2} marginTop={1}><Text color="cyan" italic>{request.question}</Text></Box>}

      {request.kind === 'tool_approval' && (
        <Box marginLeft={2} marginTop={1}>
          <Text color="gray" dimColor>
            Keyboard (this is a terminal — no mouse): single key, not the word “continue”.
          </Text>
        </Box>
      )}

      {/* Buttons */}
      <Box marginLeft={2} marginTop={1} gap={1}>
        {buttons.map((btn) => (
          <Box key={btn.key} borderStyle="round" borderColor={btn.color} paddingX={1}>
            <Text color={btn.color}>
              <Text bold color="white">[{btn.key.toUpperCase()}]</Text>
              <Text dimColor> press </Text>
              <Text bold color="white">{btn.key}</Text>
              <Text dimColor> · </Text>
              <Text>{btn.label}</Text>
            </Text>
          </Box>
        ))}
        {request.kind === 'clarification' && (
          <Box borderStyle="round" borderColor="white" paddingX={1}>
            <Text color="white"><Text bold color="white">[C]</Text> Custom…</Text>
          </Box>
        )}
      </Box>

      {/* Esc hint */}
      <Box marginLeft={2} marginTop={1}>
        <Text color="gray" dimColor>
          Enter = default ({hitlDefaultDecision(request.kind, request.default)}) · Esc = reject / default
          {request.kind === 'clarification' ? ' · C = type your own answer' : ''}
        </Text>
      </Box>
    </Box>
  )
}
