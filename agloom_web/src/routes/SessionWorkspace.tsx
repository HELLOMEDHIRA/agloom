/**
 * SessionWorkspace — the main orchestration workspace.
 *
 * Three-panel layout (responsive):
 *   Left sidebar  — navigation + session list + settings
 *   Center (main) — chat + active turn streaming
 *   Right panel   — runtime visualization tab group:
 *                     Runtime Graph | Worker Tree | Execution Trace | Artifacts
 */
import React, { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useAGPClient } from '../lib/agp/client.js'
import { useAGPStream } from '../lib/hooks/useAGPStream.js'
import { WorkspaceLayout } from '../components/workspace/WorkspaceLayout.js'
import { SessionSidebar } from '../components/workspace/SessionSidebar.js'
import { ChatPane } from '../components/chat/ChatPane.js'
import { RuntimePanel } from '../components/runtime/RuntimePanel.js'
import { ArtifactViewer } from '../components/artifacts/ArtifactViewer.js'

export type RightTab = 'graph' | 'workers' | 'trace' | 'artifacts'

export function SessionWorkspace(): React.ReactElement {
  const { sessionId } = useParams<{ sessionId: string }>()
  const client = useAGPClient()

  // Wire AGP events → store
  useAGPStream(client)

  const [rightTab, setRightTab] = useState<RightTab>('graph')
  const thread = `t_${sessionId ?? 'default'}`

  return (
    <WorkspaceLayout
      leftSlot={<SessionSidebar />}
      centerSlot={
        <ChatPane client={client} thread={thread} />
      }
      rightSlot={
        rightTab === 'artifacts'
          ? <ArtifactViewer />
          : <RuntimePanel activeTab={rightTab} onTabChange={setRightTab} />
      }
      rightTab={rightTab}
      onRightTabChange={setRightTab}
    />
  )
}
