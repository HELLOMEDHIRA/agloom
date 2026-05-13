/** MetricsPanel — right-hand session telemetry card. */

import React, { useEffect, useMemo, useState } from 'react'
import { Box, Text } from 'ink'
import { useSessionStore, type MetricTokensSlice, type ToolCall } from '../store/session.js'
import { fmtDuration, fmtTokens, fmtUsd, shortenMiddle, truncate } from '../utils/format.js'

const rollupPhases = (history: MetricTokensSlice[]): Map<string, { input: number; output: number }> => {
  const m = new Map<string, { input: number; output: number }>()
  for (const h of history) {
    const key = (h.phase ?? '').trim() || '—'
    const cur = m.get(key) ?? { input: 0, output: 0 }
    cur.input += h.input
    cur.output += h.output
    m.set(key, cur)
  }
  return m
}

const collectRecentTools = (
  completedTurns: { toolCalls: ToolCall[] }[],
  activeToolCalls: ToolCall[] | undefined,
  completedCount: number,
  max: number,
): Array<{ turnLabel: string; tc: ToolCall }> => {
  const rows: Array<{ turnLabel: string; tc: ToolCall }> = []
  completedTurns.forEach((t, i) => {
    for (const tc of t.toolCalls) rows.push({ turnLabel: `${i + 1}`, tc })
  })
  if (activeToolCalls?.length) {
    const label = `${completedCount + 1}`
    for (const tc of activeToolCalls) rows.push({ turnLabel: label, tc })
  }
  return rows.slice(-max)
}

const STATUS_DOT: Record<ToolCall['status'], string> = {
  pending: '○',
  done: '●',
  error: '✗',
}

const fmtTime = (iso: string | null): string => {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) }
  catch { return iso }
}

interface Props {
  thread: string
  width: number
}

export const MetricsPanel = ({ thread, width }: Props): React.ReactElement => {
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const sessionId = useSessionStore((s) => s.sessionId)
  const sessionOpenedAtMs = useSessionStore((s) => s.sessionOpenedAtMs)
  const sessionStartedAt = useSessionStore((s) => s.sessionStartedAt)
  const sessionUpdatedAt = useSessionStore((s) => s.sessionUpdatedAt)
  const runtimeVersion = useSessionStore((s) => s.runtimeVersion)
  const model = useSessionStore((s) => s.model)
  const completedTurns = useSessionStore((s) => s.completedTurns)
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const totalIn = useSessionStore((s) => s.totalInputTokens)
  const totalOut = useSessionStore((s) => s.totalOutputTokens)
  const turnIn = useSessionStore((s) => s.turnInputTokens)
  const turnOut = useSessionStore((s) => s.turnOutputTokens)
  const metricsHistory = useSessionStore((s) => s.metricsHistory)
  const totalCostUsd = useSessionStore((s) => s.totalCostUsd)
  const status = useSessionStore((s) => s.status)
  const protocolNotes = useSessionStore((s) => s.protocolNotes)
  const toolNames = useSessionStore((s) => s.toolNames)
  const memoryEnabled = useSessionStore((s) => s.memoryEnabled)
  const skillsEnabled = useSessionStore((s) => s.skillsEnabled)
  const harnessEnabled = useSessionStore((s) => s.harnessEnabled)
  const cliToolsCount = useSessionStore((s) => s.cliToolsCount)
  const mcpServerNames = useSessionStore((s) => s.mcpServerNames)
  const autoApprovedTools = useSessionStore((s) => s.autoApprovedTools)
  const filesUpdated = useSessionStore((s) => s.filesUpdated)

  const uptimeMs = sessionOpenedAtMs ? nowMs - sessionOpenedAtMs : 0
  const turnCount = completedTurns.length + (activeTurn ? 1 : 0)
  const innerW = Math.max(22, width - 2)
  const sid = sessionId ? shortenMiddle(sessionId, Math.min(28, width - 2)) : '—'
  const th = shortenMiddle(thread, Math.min(24, width - 2))

  const phaseRows = useMemo(() => {
    const rollup = rollupPhases(metricsHistory)
    const sorted = [...rollup.entries()].sort((a, b) => {
      const ta = a[1].input + a[1].output
      const tb = b[1].input + b[1].output
      return tb - ta
    })
    return sorted.slice(0, 6)
  }, [metricsHistory])

  const toolRows = useMemo(
    () => collectRecentTools(completedTurns, activeTurn?.toolCalls, completedTurns.length, 12),
    [completedTurns, activeTurn?.toolCalls],
  )

  return (
    <Box flexDirection="column" width={width} borderStyle="round" borderColor="cyan" paddingX={1}>
      <Text bold color="cyan">Session</Text>
      <Text color="gray" dimColor>
        {runtimeVersion ? `rt ${runtimeVersion}` : ' '}
        {model ? ` · ${truncate(model, innerW - 12)}` : ''}
      </Text>

      {/* ── Session Info ─────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">Identity</Text>
        <Text color="gray">session</Text>
        <Text color="white">{sid}</Text>
        <Text color="gray">thread</Text>
        <Text color="white">{th}</Text>
        <Text color="gray">started</Text>
        <Text color="white">{fmtTime(sessionStartedAt)}</Text>
        <Text color="gray">updated</Text>
        <Text color="white">{fmtTime(sessionUpdatedAt)}</Text>
      </Box>

      {/* ── Status Toggles ────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">Features</Text>
        <Text>
          <Text color="gray">memory </Text>
          <Text color={memoryEnabled === true ? 'green' : memoryEnabled === false ? 'red' : 'gray'}>
            {memoryEnabled === true ? '✓ ON' : memoryEnabled === false ? '✗ OFF' : '—'}
          </Text>
          <Text color="gray">  skills </Text>
          <Text color={skillsEnabled === true ? 'green' : skillsEnabled === false ? 'red' : 'gray'}>
            {skillsEnabled === true ? '✓ ON' : skillsEnabled === false ? '✗ OFF' : '—'}
          </Text>
        </Text>
        <Text>
          <Text color="gray">cli tools </Text>
          <Text color={cliToolsCount != null && cliToolsCount > 0 ? 'green' : 'gray'}>
            {cliToolsCount != null ? `${cliToolsCount} tools` : '—'}
          </Text>
        </Text>
        <Text>
          <Text color="gray">harness </Text>
          <Text color={harnessEnabled === true ? 'green' : harnessEnabled === false ? 'red' : 'gray'}>
            {harnessEnabled === true ? '✓ ON' : harnessEnabled === false ? '✗ OFF' : '—'}
          </Text>
        </Text>
      </Box>

      {/* ── Activity ──────────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">Activity</Text>
        <Text><Text color="gray">uptime </Text><Text color="yellow">{sessionOpenedAtMs ? fmtDuration(uptimeMs) : '—'}</Text></Text>
        <Text><Text color="gray">turns </Text><Text color="yellow">{turnCount}</Text><Text color="gray"> · </Text><Text color="gray" dimColor>{status}</Text></Text>
      </Box>

      {/* ── Tokens ────────────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">Tokens</Text>
        <Text>
          <Text color="gray">session </Text>
          <Text color="green">{fmtTokens(totalIn)}↑</Text>
          <Text color="gray"> </Text>
          <Text color="blue">{fmtTokens(totalOut)}↓</Text>
          <Text color="gray" dimColor> ({totalIn + totalOut} Σ)</Text>
        </Text>
        {activeTurn && (
          <Text>
            <Text color="gray">this turn </Text>
            <Text color="green">{fmtTokens(turnIn)}↑</Text>
            <Text color="gray"> </Text>
            <Text color="blue">{fmtTokens(turnOut)}↓</Text>
          </Text>
        )}
        {completedTurns.length > 0 && (
          <Text color="gray" dimColor>
            last answer · {completedTurns.at(-1)?.tokens != null ? `${completedTurns.at(-1)!.tokens} tok` : '—'}
          </Text>
        )}
      </Box>

      {/* ── Cost ──────────────────────────────────────────────────── */}
      {totalCostUsd > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">Cost</Text>
          <Text color="yellow">{fmtUsd(totalCostUsd)} est.</Text>
        </Box>
      )}

      {/* ── By Phase ──────────────────────────────────────────────── */}
      {phaseRows.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">By phase</Text>
          {phaseRows.map(([phase, v]) => (
            <Text key={phase}>
              <Text color="magenta">{truncate(phase, 14).padEnd(14)}</Text>
              <Text color="green">{fmtTokens(v.input)}↑</Text>
              <Text color="gray"> </Text>
              <Text color="blue">{fmtTokens(v.output)}↓</Text>
            </Text>
          ))}
        </Box>
      )}

      {/* ── MCP Servers ────────────────────────────────────────────── */}
      {mcpServerNames.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">MCP servers</Text>
          {mcpServerNames.map((n, i) => (
            <Text key={i} color="cyan" dimColor>◈ {n}</Text>
          ))}
        </Box>
      )}

      {/* ── Files Updated ─────────────────────────────────────────── */}
      {filesUpdated.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">Files updated</Text>
          {filesUpdated.slice(-6).map((f, i) => (
            <Text key={i} color="green" dimColor>✓ {truncate(f, innerW - 2)}</Text>
          ))}
        </Box>
      )}

      {/* ── Auto-Approved Tools ────────────────────────────────────── */}
      {autoApprovedTools.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">Auto-approved</Text>
          <Text color="gray" dimColor>{autoApprovedTools.join(', ')}</Text>
        </Box>
      )}

      {/* ── Recent Tools ──────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">Tools (recent)</Text>
        {toolRows.length === 0 ? (
          <Text color="gray" dimColor>—</Text>
        ) : (
          toolRows.map(({ turnLabel, tc }) => (
            <Box key={tc.id} flexDirection="column">
              <Text>
                <Text color="gray">T{turnLabel} </Text>
                <Text color={tc.status === 'error' ? 'red' : tc.status === 'pending' ? 'yellow' : 'green'}>
                  {STATUS_DOT[tc.status]}
                </Text>
                <Text bold> {truncate(tc.tool, 18)}</Text>
                {tc.durationMs !== undefined ? (
                  <Text color="gray" dimColor> {fmtDuration(tc.durationMs)}</Text>
                ) : tc.status === 'pending' ? (
                  <Text color="gray" dimColor> …</Text>
                ) : null}
              </Text>
            </Box>
          ))
        )}
      </Box>

      {/* ── Wire Notes ────────────────────────────────────────────── */}
      {protocolNotes.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">Wire notes</Text>
          {protocolNotes.slice(-8).map((line, i) => (
            <Text key={`${i}-${line.slice(0, 20)}`} color="gray" dimColor>
              {truncate(line, innerW)}
            </Text>
          ))}
        </Box>
      )}
    </Box>
  )
}
