/**
 * MetricsPanel — recharts-based charts for token usage, tool latency, node timings.
 */
import React from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import type { SessionMetrics } from '../../lib/agp/obsApi.js'
import { fmtTokens, fmtDuration } from '../../lib/utils/cn.js'

interface Props { metrics?: SessionMetrics }

const COLORS = ['#6366f1','#22d3ee','#a78bfa','#34d399','#fbbf24','#f87171']

export const MetricsPanel = ({ metrics }: Props): React.ReactElement => {
  if (!metrics) return <div className="flex items-center justify-center h-48 text-neutral-600 text-sm">Loading metrics…</div>

  const tokenData = [
    { name: 'Input',  tokens: metrics.total_input_tokens },
    { name: 'Output', tokens: metrics.total_output_tokens },
  ]

  const toolData = metrics.tools.map((t) => ({
    name: t.tool,
    calls: t.call_count,
    avg_ms: Math.round(t.avg_duration_ms),
    errors: t.error_count,
  }))

  const nodeData = metrics.nodes.map((n) => ({
    name: n.node,
    calls: n.call_count,
    avg_ms: Math.round(n.avg_duration_ms),
  }))

  return (
    <div className="h-full overflow-y-auto p-4 space-y-6">
      {/* Summary row */}
      <div className="grid grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: 'Turns',        value: metrics.total_turns },
          { label: 'Events',       value: metrics.total_events },
          { label: 'Tokens in',    value: fmtTokens(metrics.total_input_tokens) },
          { label: 'Tokens out',   value: fmtTokens(metrics.total_output_tokens) },
          { label: 'HITL gates',   value: metrics.hitl_gates },
          { label: 'Errors',       value: metrics.transient_errors + metrics.fatal_errors },
        ].map(({ label, value }) => (
          <div key={label} className="bg-neutral-900 border border-neutral-800 rounded-xl p-3 flex flex-col gap-1">
            <span className="text-xs text-neutral-500">{label}</span>
            <span className="text-lg font-bold text-white">{value}</span>
          </div>
        ))}
      </div>

      {/* Token distribution */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
        <h3 className="text-xs font-semibold text-neutral-400 mb-4">Token distribution</h3>
        <ResponsiveContainer width="100%" height={160}>
          <PieChart>
            <Pie data={tokenData} dataKey="tokens" nameKey="name" cx="50%" cy="50%" outerRadius={60} label={({ name, value }) => `${name}: ${fmtTokens(Number(value))}`} labelLine={false}>
              {tokenData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]!} />)}
            </Pie>
            <Legend />
            <Tooltip formatter={(v) => fmtTokens(Number(v))} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Tool latency */}
      {toolData.length > 0 && (
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-neutral-400 mb-4">Tool avg latency (ms)</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={toolData} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#737373' }} />
              <YAxis tick={{ fontSize: 10, fill: '#737373' }} />
              <Tooltip contentStyle={{ background: '#171717', border: '1px solid #262626', fontSize: 11 }} />
              <Bar dataKey="avg_ms" fill="#6366f1" radius={[3, 3, 0, 0]} name="avg ms" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* LangGraph node timings */}
      {nodeData.length > 0 && (
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-4">
          <h3 className="text-xs font-semibold text-neutral-400 mb-4">LangGraph node avg duration (ms)</h3>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={nodeData} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#737373' }} />
              <YAxis tick={{ fontSize: 10, fill: '#737373' }} />
              <Tooltip contentStyle={{ background: '#171717', border: '1px solid #262626', fontSize: 11 }} />
              <Bar dataKey="avg_ms" fill="#a78bfa" radius={[3, 3, 0, 0]} name="avg ms" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Session duration note */}
      {metrics.session_duration_ms && (
        <p className="text-xs text-neutral-600 text-center">Session duration: {fmtDuration(metrics.session_duration_ms)}</p>
      )}
    </div>
  )
}
