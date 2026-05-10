/**
 * RuntimeGraph — live LangGraph node visualization using React Flow (@xyflow/react).
 *
 * Consumes graph.node.enter / graph.node.exit AGP events from the store.
 * Nodes are laid out left-to-right in execution order.
 * Active nodes pulse; completed nodes are solid green; failed nodes are red.
 */
import React, { useMemo } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  BackgroundVariant,
  MarkerType,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useSessionStore } from '../../store/session.js'

export const RuntimeGraph = (): React.ReactElement => {
  const activeGraphNodes = useSessionStore((s) => s.activeTurn?.graphNodes)
  const lastGraphNodes = useSessionStore((s) => s.completedTurns.at(-1)?.graphNodes)

  const { nodes, edges } = useMemo(() => {
    const graphNodes = activeGraphNodes ?? lastGraphNodes ?? []
    const n: Node[] = graphNodes.map((gn, i) => ({
      id: `${gn.nodeId}_${i}`,
      position: { x: i * 160, y: 80 },
      data: {
        label: gn.nodeId,
        durationMs: gn.durationMs,
        active: !gn.exitAt,
      },
      type: 'default',
      style: {
        background: !gn.exitAt
          ? '#1e1b4b'  // active — indigo-950
          : gn.durationMs
          ? '#052e16'  // completed — green-950
          : '#1c1917',
        border: `1px solid ${!gn.exitAt ? '#6366f1' : gn.durationMs ? '#16a34a' : '#44403c'}`,
        borderRadius: 8,
        color: '#e5e7eb',
        fontSize: 11,
        fontFamily: 'monospace',
        padding: '6px 10px',
        minWidth: 100,
      },
    }))

    const e: Edge[] = graphNodes.slice(1).map((_, i) => ({
      id: `e_${i}`,
      source: `${graphNodes[i]!.nodeId}_${i}`,
      target: `${graphNodes[i + 1]!.nodeId}_${i + 1}`,
      animated: !graphNodes[i + 1]!.exitAt,
      style: { stroke: '#4b5563' },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#4b5563' },
    }))

    return { nodes: n, edges: e }
  }, [activeGraphNodes, lastGraphNodes])

  const graphNodes = activeGraphNodes ?? lastGraphNodes ?? []

  if (graphNodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-neutral-600 text-sm p-6 text-center">
        LangGraph nodes appear here when the agent runs.
      </div>
    )
  }

  return (
    <div className="h-full w-full bg-neutral-950">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} color="#1f1f1f" />
        <Controls className="[&_button]:bg-neutral-800 [&_button]:border-neutral-700 [&_button]:text-neutral-400" />
      </ReactFlow>
    </div>
  )
}
