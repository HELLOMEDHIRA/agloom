/** HITLPrompt — replaces the normal input bar when a HITL gate is pending.
 * Kind-aware shortcuts (AGP `command.hitl.respond` decisions): - tool_approval / pattern_approval / worker_approval: y/yes→accept, n/no→reject, a→allowlist - react_recovery: r/retry→retry, s/stop→stop - clarification: free text → decision `accept` + `text` payload (wire contract) Escape or empty submit sends `request.default` when present, else kind-safe fallback (`reject` for gates, `cancelled` for clarification).
 */

import React, { useState } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'
import type { HITLRequest } from '../store/session.js'
import type { AGPBridge } from '../runtime/bridge.js'
import { truncate } from '../utils/format.js'

interface Props {
  request: HITLRequest
  bridge: AGPBridge
}

const hitlDefaultDecision = (kind: string, wireDefault?: string): string => {
  if (kind === 'clarification') return wireDefault ?? 'cancelled'
  return wireDefault ?? 'reject'
}

const resolveNonClarificationDecision = (kind: string, options: string[], raw: string): string => {
  const t = raw.trim().toLowerCase()
  if (kind === 'tool_approval' || kind === 'pattern_approval' || kind === 'worker_approval') {
    if (t === 'y' || t === 'yes') return 'accept'
    if (t === 'n' || t === 'no') return 'reject'
    if (t === 'a' || t === 'allowlist') return 'allowlist'
    const canon = options.find((o) => o.toLowerCase() === t)
    return canon ?? raw.trim()
  }
  if (kind === 'react_recovery') {
    if (t === 'r' || t === 'retry') return 'retry'
    if (t === 's' || t === 'stop') return 'stop'
    const canon = options.find((o) => o.toLowerCase() === t)
    return canon ?? raw.trim()
  }
  const canon = options.find((o) => o.toLowerCase() === t)
  return canon ?? raw.trim()
}

const formatOptionHints = (kind: string, options: string[]): string => {
  if (kind === 'clarification') {
    return 'free-text answer · Enter = submit · Esc = cancel'
  }
  if (kind === 'react_recovery') {
    return options.map((o) => (o === 'retry' ? 'r(etry)' : o === 'stop' ? 's(top)' : o)).join('  ·  ')
  }
  return options
    .map((o) => {
      if (o === 'accept') return 'y(es) · accept'
      if (o === 'reject') return 'n(o) · reject'
      if (o === 'allowlist') return 'a · allowlist'
      return o
    })
    .join('  ·  ')
}

const placeholderForKind = (kind: string): string => {
  if (kind === 'clarification') return 'Your answer…'
  if (kind === 'react_recovery') return 'r / s · or retry | stop'
  return 'y / n / a · or accept | reject | allowlist'
}

export const HITLPrompt = ({ request, bridge }: Props): React.ReactElement => {
  const [value, setValue] = useState('')

  const sendDefault = (): void => {
    bridge.hitlRespond(request.requestId, hitlDefaultDecision(request.kind, request.default))
  }

  useInput((_input, key) => {
    if (key.escape) sendDefault()
  })

  const handleSubmit = (text: string): void => {
    if (request.kind === 'clarification') {
      const answer = text.trim()
      if (!answer) {
        sendDefault()
      } else {
        bridge.hitlRespond(request.requestId, 'accept', answer)
      }
      setValue('')
      return
    }

    const trimmed = text.trim()
    if (!trimmed) {
      sendDefault()
      setValue('')
      return
    }

    const decision = resolveNonClarificationDecision(request.kind, request.options, text)
    bridge.hitlRespond(request.requestId, decision)
    setValue('')
  }

  const optionHints = formatOptionHints(request.kind, request.options)
  const escHint = hitlDefaultDecision(request.kind, request.default)

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor="yellow"
      paddingX={1}
      paddingY={0}
      marginBottom={0}
    >
      {/* Gate header */}
      <Box>
        <Text bold color="yellow">
          ⚠ HITL:{' '}
        </Text>
        <Text bold>{request.kind}</Text>
        {request.tool && (
          <Text color="gray" dimColor>
            {' '}
            · {request.tool}
          </Text>
        )}
      </Box>

      {/* Detail */}
      {request.detail && (
        <Box marginLeft={2}>
          <Text color="white">{truncate(request.detail, 100)}</Text>
        </Box>
      )}

      {/* Question */}
      {request.question && (
        <Box marginLeft={2}>
          <Text color="cyan" italic>
            {request.question}
          </Text>
        </Box>
      )}

      {/* Options */}
      <Box marginLeft={2}>
        <Text color="gray" dimColor>
          [{optionHints}]  Esc = {escHint}
        </Text>
      </Box>

      {/* Input */}
      <Box marginTop={0}>
        <Text color="yellow" bold>
          {'  ❯ '}
        </Text>
        <TextInput
          value={value}
          onChange={setValue}
          onSubmit={handleSubmit}
          placeholder={placeholderForKind(request.kind)}
        />
      </Box>
    </Box>
  )
}
