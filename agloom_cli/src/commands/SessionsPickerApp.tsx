/** Session picker (`agloom sessions`): `@inkjs/ui` Select; Esc cancels. */

import React from 'react'
import { Box, Text, useInput, useApp } from 'ink'
import { Select } from '@inkjs/ui'
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

  useInput((_input, key) => {
    if (key.escape || (key.ctrl && _input === 'c')) {
      onChosen(null)
      exit()
    }
  })

  const visible = Math.min(10, Math.max(3, sessions.length))

  return (
    <Box flexDirection="column" paddingX={1} paddingY={1}>
      <Text bold color="cyan">
        agloom — resume a session
      </Text>
      <Text dimColor>↑/↓ highlight · Enter resume · Esc / Ctrl+C cancel</Text>
      <Box marginTop={1} flexDirection="column">
        <Select
          visibleOptionCount={visible}
          options={sessions.map((s, idx) => ({
            value: s.id,
            label: `${String(idx + 1).padStart(2, ' ')}. ${truncate(s.id, 40)} · ${fmtWhen(s.startedAt)} · ${truncate(s.model, 32)} · ${s.turns} turns · ${truncate(s.thread, 24)}`,
          }))}
          onChange={(id) => {
            const row = sessions.find((x) => x.id === id)
            if (row) {
              onChosen(row)
              exit()
            }
          }}
        />
      </Box>
    </Box>
  )
}
