/**
 * HITLPrompt — replaces the normal input bar when a HITL gate is pending.
 *
 * The user types a decision key (y / n / d / a custom value) and presses
 * Enter to respond. Pressing Escape or /skip sends the default decision.
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

export function HITLPrompt({ request, bridge }: Props): React.ReactElement {
  const [value, setValue] = useState('')

  useInput((_input, key) => {
    if (key.escape) {
      // Escape → send default or 'deny'
      const decision = request.default ?? 'deny'
      bridge.hitlRespond(request.requestId, decision)
    }
  })

  const handleSubmit = (text: string) => {
    const trimmed = text.trim().toLowerCase()
    if (!trimmed) {
      const decision = request.default ?? 'deny'
      bridge.hitlRespond(request.requestId, decision)
      return
    }

    // Map common shortcuts
    const decision =
      trimmed === 'y' || trimmed === 'yes'
        ? 'accept'
        : trimmed === 'n' || trimmed === 'no'
          ? 'deny'
          : trimmed === 'd' || trimmed === 'defer'
            ? 'defer'
            : trimmed

    bridge.hitlRespond(request.requestId, decision)
    setValue('')
  }

  const optionHints = request.options
    .map((o) => {
      const short = o[0]?.toLowerCase()
      if (short === 'a' || o === 'accept') return 'y(es)'
      if (short === 'd' || o === 'deny') return 'n(o)'
      if (o === 'defer') return 'd(efer)'
      return o
    })
    .join('  /  ')

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
          [{optionHints}]  Esc = {request.default ?? 'deny'}
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
          placeholder="y / n / d / custom…"
        />
      </Box>
    </Box>
  )
}
