/** MetricsPanel — right-hand session telemetry card. */

import React, { useEffect, useMemo, useState } from 'react'
import { Box, Text } from 'ink'
import { Badge } from '@inkjs/ui'
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

type RunStatus = 'idle' | 'running' | 'thinking' | 'hitl' | 'error' | 'exited'

const RUN_STATUS_BADGE_COLOR: Record<RunStatus, 'green' | 'yellow' | 'magenta' | 'red' | 'gray'> = {
  idle: 'green',
  running: 'yellow',
  thinking: 'magenta',
  hitl: 'yellow',
  error: 'red',
  exited: 'gray',
}

const TOOL_STATUS_BADGE_COLOR: Record<ToolCall['status'], 'yellow' | 'green' | 'red'> = {
  pending: 'yellow',
  done: 'green',
  error: 'red',
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
  const sessionMemoryMode = useSessionStore((s) => s.sessionMemoryMode)
  const skillsEnabled = useSessionStore((s) => s.skillsEnabled)
  const harnessEnabled = useSessionStore((s) => s.harnessEnabled)
  const cliToolsEnabled = useSessionStore((s) => s.cliToolsEnabled)
  const cliToolsCount = useSessionStore((s) => s.cliToolsCount)
  const mcpServerNames = useSessionStore((s) => s.mcpServerNames)
  const mcpServerRows = useSessionStore((s) => s.mcpServerRows)
  const autoApprovedTools = useSessionStore((s) => s.autoApprovedTools)
  const filesUpdated = useSessionStore((s) => s.filesUpdated)

  const uptimeMsRaw = sessionOpenedAtMs ? nowMs - sessionOpenedAtMs : 0
  const uptimeMs = sessionOpenedAtMs ? Math.max(0, uptimeMsRaw) : 0
  const turnCount = completedTurns.length + (activeTurn ? 1 : 0)
  const innerW = Math.max(18, width - 4)
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

  const mcpRollup = useMemo(() => {
    if (mcpServerRows.length > 0) {
      const okRows = mcpServerRows.filter((r) => r.ok)
      const toolSum = mcpServerRows.reduce((sum, r) => sum + (r.ok ? r.toolCount : 0), 0)
      const okSrv = okRows.length
      const totalSrv = mcpServerRows.length
      return {
        kind: 'live' as const,
        okServers: okSrv,
        totalServers: totalSrv,
        tools: toolSum,
        allServersOk: okSrv === totalSrv && totalSrv > 0,
        hasFail: okSrv < totalSrv,
      }
    }
    if (mcpServerNames.length > 0) {
      return { kind: 'pending' as const, totalServers: mcpServerNames.length }
    }
    return { kind: 'none' as const }
  }, [mcpServerRows, mcpServerNames])

  return (
    <Box
      flexDirection="column"
      width={width}
      flexShrink={0}
      borderStyle="round"
      borderColor="cyan"
      paddingX={1}
      paddingY={1}
    >
      <Text bold color="cyan">Session</Text>
      <Text color="gray" dimColor>
        {runtimeVersion ? `rt ${runtimeVersion}` : ' '}
        {model ? ` · ${truncate(model, innerW - 12)}` : ''}
      </Text>

      {/* ── Session Info ─────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column" width={innerW}>
        <Text bold color="white">Identity</Text>
        <Text>
          <Text color="gray">session </Text>
          <Text color="white">{sid}</Text>
        </Text>
        <Text>
          <Text color="gray">thread </Text>
          <Text color="white">{th}</Text>
        </Text>
        <Text>
          <Text color="gray">started </Text>
          <Text color="white">{fmtTime(sessionStartedAt)}</Text>
          <Text color="gray"> · updated </Text>
          <Text color="white">{fmtTime(sessionUpdatedAt)}</Text>
        </Text>
      </Box>

      {/* ── Status Toggles ────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column" width={innerW}>
        <Text bold color="white">Features</Text>
        <Text>
          <Text color="gray">memory </Text>
          <Text
            color={
              sessionMemoryMode === 'sqlite' ||
              sessionMemoryMode === 'in-memory' ||
              sessionMemoryMode === 'off' ||
              memoryEnabled === true
                ? 'green'
                : sessionMemoryMode === 'none' || memoryEnabled === false
                  ? 'red'
                  : 'gray'
            }
          >
            {sessionMemoryMode != null && sessionMemoryMode !== ''
              ? sessionMemoryMode === 'none'
                ? '✗ none'
                : sessionMemoryMode === 'off'
                  ? '✓ in-memory'
                  : `✓ ${sessionMemoryMode}`
              : memoryEnabled === true
                ? '✓ ON'
                : memoryEnabled === false
                  ? '✗ OFF'
                  : '—'}
          </Text>
        </Text>
        <Text>
          <Text color="gray">skills </Text>
          <Text color={skillsEnabled === true ? 'green' : skillsEnabled === false ? 'red' : 'gray'}>
            {skillsEnabled === true ? '✓ ON (LT store)' : skillsEnabled === false ? '✗ OFF' : '—'}
          </Text>
        </Text>
        <Text>
          <Text color="gray">cli tools </Text>
          <Text color={cliToolsCount != null && cliToolsCount > 0 ? 'green' : cliToolsEnabled === false ? 'red' : 'gray'}>
            {cliToolsCount != null && cliToolsCount > 0
              ? `${cliToolsCount} tools`
              : cliToolsEnabled === false
                ? '✗ OFF'
                : cliToolsCount === 0
                  ? '0 tools'
                  : '—'}
          </Text>
        </Text>
        <Text>
          <Text color="gray">harness </Text>
          <Text color={harnessEnabled === true ? 'green' : harnessEnabled === false ? 'red' : 'gray'}>
            {harnessEnabled === true ? '✓ ON' : harnessEnabled === false ? '✗ OFF' : '—'}
          </Text>
        </Text>
        <Text>
          <Text color="gray">mcp </Text>
          {mcpRollup.kind === 'live' ? (
            <>
              <Text color={mcpRollup.allServersOk ? 'green' : mcpRollup.hasFail ? 'yellow' : 'gray'}>
                {mcpRollup.allServersOk ? '✓ ' : mcpRollup.hasFail ? '⚠ ' : '○ '}
              </Text>
              <Text color={mcpRollup.allServersOk ? 'green' : 'white'}>
                {mcpRollup.okServers}/{mcpRollup.totalServers} ok · {mcpRollup.tools} tools
              </Text>
            </>
          ) : mcpRollup.kind === 'pending' ? (
            <>
              <Text color="yellow">○ </Text>
              <Text color="gray">{mcpRollup.totalServers} srv · tools after connect</Text>
            </>
          ) : (
            <Text color="gray">— no servers</Text>
          )}
        </Text>
      </Box>

      {/* ── Activity ──────────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column" width={innerW}>
        <Text bold color="white">Activity</Text>
        <Text>
          <Text color="gray">uptime </Text>
          <Text color="yellow">{sessionOpenedAtMs ? fmtDuration(uptimeMs) : '—'}</Text>
          <Text color="gray"> · turns </Text>
          <Text color="yellow">{turnCount}</Text>
          <Text color="gray"> · </Text>
          <Badge color={RUN_STATUS_BADGE_COLOR[status as RunStatus] ?? 'gray'}>{status}</Badge>
        </Text>
      </Box>

      {/* ── Tokens ────────────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column" width={innerW}>
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

      <Box marginTop={1} flexDirection="column" width={innerW}>
        <Text bold color="white">Cost</Text>
        <Text color={totalCostUsd > 0 ? 'yellow' : 'gray'} dimColor={totalCostUsd <= 0}>
          {fmtUsd(totalCostUsd)}
          {totalCostUsd > 0 ? ' (session)' : ''}
        </Text>
      </Box>

      {/* ── By Phase ──────────────────────────────────────────────── */}
      {phaseRows.length > 0 && (
        <Box marginTop={1} flexDirection="column" width={innerW}>
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

      {(mcpServerRows.length > 0 || mcpServerNames.length > 0) && (
        <Box marginTop={1} flexDirection="column" width={innerW}>
          <Text bold color="white">MCP</Text>
          {mcpServerRows.length > 0 ? (
            mcpServerRows.map((r, i) => (
              <Text key={`${r.name}-${i}`} wrap="truncate-end">
                <Text color={r.ok ? 'green' : 'red'}>{r.ok ? '● ' : '○ '}</Text>
                <Text color="cyan">{truncate(r.name, 18)}</Text>
                <Text color="gray">
                  {r.ok ? ` · ${r.toolCount} tools` : ` · ${truncate(String(r.error ?? 'error'), innerW - 22)}`}
                </Text>
              </Text>
            ))
          ) : (
            mcpServerNames.map((n, i) => (
              <Text key={i} wrap="truncate-end">
                <Text color="yellow">○ </Text>
                <Text color="cyan">{truncate(n, 18)}</Text>
                <Text color="gray" dimColor> · pending (first message)</Text>
              </Text>
            ))
          )}
        </Box>
      )}

      {/* ── Files Updated ─────────────────────────────────────────── */}
      {filesUpdated.length > 0 && (
        <Box marginTop={1} flexDirection="column" width={innerW}>
          <Text bold color="white">Files updated</Text>
          {filesUpdated.slice(-6).map((f, i) => (
            <Text key={i} color="green" dimColor>✓ {truncate(f, innerW - 2)}</Text>
          ))}
        </Box>
      )}

      {/* ── Auto-Approved Tools ────────────────────────────────────── */}
      {autoApprovedTools.length > 0 && (
        <Box marginTop={1} flexDirection="column" width={innerW}>
          <Text bold color="white">Auto-approved</Text>
          <Text color="gray" dimColor>{autoApprovedTools.join(', ')}</Text>
        </Box>
      )}

      {/* ── Recent Tools ──────────────────────────────────────────── */}
      <Box marginTop={1} flexDirection="column" width={innerW}>
        <Text bold color="white">Tools (recent)</Text>
        {toolRows.length === 0 ? (
          <Text color="gray" dimColor>—</Text>
        ) : (
          toolRows.map(({ turnLabel, tc }) => (
            <Box key={tc.id} flexDirection="column">
              <Text>
                <Text color="gray">T{turnLabel} </Text>
                <Badge color={TOOL_STATUS_BADGE_COLOR[tc.status]}>{tc.status}</Badge>
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
        <Box marginTop={1} flexDirection="column" width={innerW}>
          <Text bold color="white">Wire notes</Text>
          {protocolNotes.slice(-8).map((line, i) => (
            <Text key={`${i}-${line.slice(0, 20)}`} color="gray" dimColor wrap="truncate-end">
              {truncate(line, innerW)}
            </Text>
          ))}
        </Box>
      )}
    </Box>
  )
}
