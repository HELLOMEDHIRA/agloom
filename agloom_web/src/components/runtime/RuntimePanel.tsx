/**
 * RuntimePanel — right-side panel hosting the runtime visualization tabs.
 */
import React from 'react'
import type { RightTab } from '../../routes/SessionWorkspace.js'
import { RuntimeGraph } from './RuntimeGraph.js'
import { WorkerTree } from './WorkerTree.js'
import { ExecutionTrace } from './ExecutionTrace.js'
import { ArtifactViewer } from '../artifacts/ArtifactViewer.js'

interface Props {
  activeTab: RightTab
  onTabChange: (t: RightTab) => void
}

export function RuntimePanel({ activeTab }: Props): React.ReactElement {
  switch (activeTab) {
    case 'graph':     return <RuntimeGraph />
    case 'workers':   return <WorkerTree />
    case 'trace':     return <ExecutionTrace />
    case 'artifacts': return <ArtifactViewer />
  }
}
