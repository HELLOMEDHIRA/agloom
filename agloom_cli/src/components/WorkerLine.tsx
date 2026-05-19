/** WorkerLine — renders a single worker node with status badge. */

import React from 'react'
import { Box, Text } from 'ink'
import { Badge } from '@inkjs/ui'
import type { Worker } from '../store/session.js'

const WORKER_ICON: Record<Worker['status'], string> = {
  running: '◈',
  done: '◉',
  failed: '✗',
  halted: '⊘',
}

const WORKER_BADGE_COLOR: Record<Worker['status'], 'yellow' | 'green' | 'red' | 'cyan'> = {
  running: 'yellow',
  done: 'green',
  failed: 'red',
  halted: 'cyan',
}

const haltedReasonLabel = (reason?: string | null): string => {
  if (!reason || reason === 'HALT_ALL') return 'Stopped (all workers halted)'
  return reason
}

interface Props {
  worker: Worker
}

export const WorkerLine = ({ worker }: Props): React.ReactElement => {
  const icon = WORKER_ICON[worker.status]
  const badgeColor = WORKER_BADGE_COLOR[worker.status]
  const taskStr = worker.task ? ` — ${worker.task}` : ''
  const patternStr = worker.pattern ? ` [${worker.pattern}]` : ''

  return (
    <Box flexDirection="column" marginLeft={2}>
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        <Text color={badgeColor}>{icon} </Text>
        <Badge color={badgeColor}>{worker.status}</Badge>
        <Text bold wrap="wrap">
          {worker.name}
        </Text>
        <Text color="magenta" dimColor wrap="wrap">
          {patternStr}
        </Text>
        <Text color="gray" wrap="wrap">
          {taskStr}
        </Text>
      </Box>

      {worker.status === 'done' && worker.outputPreview && (
        <Box marginLeft={3}>
          <Text color="gray" dimColor wrap="wrap">
            {worker.outputPreview}
          </Text>
        </Box>
      )}
      {worker.status === 'failed' && worker.error && (
        <Box marginLeft={3}>
          <Text color="red" dimColor wrap="wrap">
            {worker.error}
          </Text>
        </Box>
      )}
      {worker.status === 'halted' && (
        <Box marginLeft={3}>
          <Text color="cyan" dimColor wrap="wrap">
            {haltedReasonLabel(worker.error)}
            {worker.outputPreview ? ` — ${worker.outputPreview}` : ''}
          </Text>
        </Box>
      )}
    </Box>
  )
}
