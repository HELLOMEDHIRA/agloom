/** WorkerLine — renders a single worker node with status badge. */

import React from 'react'
import { Box, Text } from 'ink'
import { Badge } from '@inkjs/ui'
import type { Worker } from '../store/session.js'
import { truncate } from '../utils/format.js'

const WORKER_ICON: Record<Worker['status'], string> = {
  running: '◈',
  done: '◉',
  failed: '✗',
}

const WORKER_BADGE_COLOR: Record<Worker['status'], 'yellow' | 'green' | 'red'> = {
  running: 'yellow',
  done: 'green',
  failed: 'red',
}

interface Props {
  worker: Worker
}

export const WorkerLine = ({ worker }: Props): React.ReactElement => {
  const icon = WORKER_ICON[worker.status]
  const badgeColor = WORKER_BADGE_COLOR[worker.status]
  const taskStr = worker.task ? ` — ${truncate(worker.task, 40)}` : ''
  const patternStr = worker.pattern ? ` [${worker.pattern}]` : ''

  return (
    <Box flexDirection="column" marginLeft={2}>
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        <Text color={badgeColor}>{icon} </Text>
        <Badge color={badgeColor}>{worker.status}</Badge>
        <Text bold>{worker.name}</Text>
        <Text color="magenta" dimColor>
          {patternStr}
        </Text>
        <Text color="gray">{taskStr}</Text>
      </Box>

      {worker.status === 'done' && worker.outputPreview && (
        <Box marginLeft={3}>
          <Text color="gray" dimColor>
            {truncate(worker.outputPreview, 100)}
          </Text>
        </Box>
      )}
      {worker.status === 'failed' && worker.error && (
        <Box marginLeft={3}>
          <Text color="red" dimColor>
            {truncate(worker.error, 100)}
          </Text>
        </Box>
      )}
    </Box>
  )
}
