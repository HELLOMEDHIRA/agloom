/** WorkerLine — renders a single worker node with status badge. */

import React from 'react'
import { Box, Text } from 'ink'
import type { Worker } from '../store/session.js'
import { truncate } from '../utils/format.js'

const WORKER_ICON: Record<Worker['status'], string> = {
  running: '◈',
  done: '◉',
  failed: '✗',
}

const WORKER_COLOR: Record<Worker['status'], string> = {
  running: 'yellow',
  done: 'green',
  failed: 'red',
}

interface Props {
  worker: Worker
}

export const WorkerLine = ({ worker }: Props): React.ReactElement => {
  const icon = WORKER_ICON[worker.status]
  const color = WORKER_COLOR[worker.status]
  const taskStr = worker.task ? ` — ${truncate(worker.task, 40)}` : ''
  const patternStr = worker.pattern ? ` [${worker.pattern}]` : ''

  return (
    <Box flexDirection="column" marginLeft={2}>
      <Box>
        <Text color={color as Parameters<typeof Text>[0]['color']}>{icon} </Text>
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
