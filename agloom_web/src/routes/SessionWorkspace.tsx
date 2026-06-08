/** SessionWorkspace — the main orchestration workspace.
 * Three-panel layout (responsive): Left sidebar — navigation + session list + settings Center (main) — chat + active turn streaming Right panel — runtime visualization tab group: Runtime Graph | Worker Tree | Execution Trace | Artifacts
 */
import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAGPClient } from '../lib/agp/client.js'
import { useAGPStream } from '../lib/hooks/useAGPStream.js'
import { WorkspaceLayout } from '../components/workspace/WorkspaceLayout.js'
import { SessionSidebar } from '../components/workspace/SessionSidebar.js'
import { ChatPane } from '../components/chat/ChatPane.js'
import { RuntimePanel } from '../components/runtime/RuntimePanel.js'
import { ArtifactViewer } from '../components/artifacts/ArtifactViewer.js'

export type RightTab = 'graph' | 'workers' | 'trace' | 'artifacts'

export const SessionWorkspace = (): React.ReactElement => {
  const { sessionId } = useParams<{ sessionId: string }>()
  const client = useAGPClient()
  const navigate = useNavigate()

  // Wire AGP events → store
  useAGPStream(client)

  useEffect(() => {
    const off = client.onEvent((evt) => {
      if (evt.type !== 'runtime.session.renamed') return
      if (!sessionId || evt.data.from_session_id !== sessionId) return
      navigate(`/session/${evt.data.to_session_id}`, { replace: true })
    })
    return off
  }, [client, sessionId, navigate])

  useEffect(() => {
    const off = client.onStatus((st) => {
      if (st === 'open') client.send({ type: 'command.session.list', data: {} })
    })
    if (client.status === 'open') client.send({ type: 'command.session.list', data: {} })
    return off
  }, [client])

  const [rightTab, setRightTab] = useState<RightTab>('graph')
  const thread = `t_${sessionId ?? 'default'}`

  return (
    <WorkspaceLayout
      agpClient={client}
      leftSlot={<SessionSidebar />}
      centerSlot={
        <ChatPane client={client} thread={thread} workspaceSessionId={sessionId ?? 'default'} />
      }
      rightSlot={
        rightTab === 'artifacts'
          ? <ArtifactViewer />
          : <RuntimePanel activeTab={rightTab} />
      }
      rightTab={rightTab}
      onRightTabChange={setRightTab}
    />
  )
}
