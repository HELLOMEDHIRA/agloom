/**
 * Full-screen session picker for ``agloom sessions`` — keyboard navigation, no readline.
 */

import React, { useState } from 'react'
import { Box, Text, useInput, useApp } from 'ink'
import { truncate } from '../utils/format.js'
import type { SessionInfo } from './sessionsLoad.js'

export type SessionRow = SessionInfo

const fmtWhen = (iso: string): string => {
  if (!iso || iso === '—') return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return truncate(iso, 18)
  }
}

export interface SessionsPickerAppProps {
  sessions: SessionRow[]
  /** Called with the chosen row, or ``null`` if the user cancels. */
  onChosen: (row: SessionRow | null) => void
}

export const SessionsPickerApp = ({ sessions, onChosen }: SessionsPickerAppProps): React.ReactElement => {
  const { exit } = useApp()
  const [i, setI] = useState(0)

  useInput((ch, key) => {
    if (key.upArrow) {
      setI((x) => Math.max(0, x - 1))
      return
    }
    if (key.downArrow) {
      setI((x) => Math.min(sessions.length - 1, x + 1))
      return
    }
    if (key.return) {
      const row = sessions[i]
      if (row) onChosen(row)
      exit()
      return
    }
    if (key.escape || (key.ctrl && ch === 'c')) {
      onChosen(null)
      exit()
      return
    }
    if (ch >= '1' && ch <= '9') {
      const n = parseInt(ch, 10) - 1
      if (n >= 0 && n < sessions.length) setI(n)
    }
  })

  const cur = sessions[i]

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color="cyan">
        agloom — resume a session
      </Text>
      <Text dimColor>
        ↑/↓ move · 1–9 jump to row · Enter resume · Esc / Ctrl+C cancel
      </Text>
      <Box marginTop={1} flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1}>
        {sessions.map((s, idx) => {
          const sel = idx === i
          return (
            <Box key={s.id} flexDirection="row" minHeight={1}>
              <Text color={sel ? 'green' : 'gray'}>{sel ? '▶ ' : '  '}</Text>
              <Text color={sel ? 'white' : 'gray'} bold={sel}>
                {(idx + 1).toString().padStart(2, ' ')}.
              </Text>
              <Text> </Text>
              <Box flexDirection="column" flexGrow={1}>
                <Text bold={sel} color={sel ? 'white' : 'gray'}>
                  {truncate(s.id, 56)}
                </Text>
                <Text dimColor color={sel ? 'cyan' : 'gray'}>
                  {fmtWhen(s.startedAt)} · {truncate(s.model, 36)} · turns {s.turns} · {s.transport}
                </Text>
              </Box>
            </Box>
          )
        })}
      </Box>
      {cur && (
        <Box marginTop={1} flexDirection="column" borderStyle="single" borderColor="gray" paddingX={1}>
          <Text dimColor>thread</Text>
          <Text>{truncate(cur.thread, 72)}</Text>
          <Text dimColor>provider</Text>
          <Text>{truncate(cur.provider, 72)}</Text>
        </Box>
      )}
    </Box>
  )
}
