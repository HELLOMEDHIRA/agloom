/** MetricsPanel — right-hand session telemetry card (scrollable when content exceeds terminal height). */

import React, { useMemo } from 'react'
import { Box, Text } from 'ink'
import { Badge } from '@inkjs/ui'
import { useSessionStore, type MetricTokensSlice, type ToolCall } from '../store/session.js'
import { fmtDuration, fmtTokens, fmtUsd, shortenMiddle, truncate } from '../utils/format.js'
import { ScrollableColumn } from './ScrollableColumn.js'

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
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

const spacer = (key: string): React.ReactElement => (
  <Text key={key} color="gray" dimColor>
    {' '}
  </Text>
)

interface Props {
  thread: string
  width: number
  /** Total panel height in terminal rows (border + title + scroll body). */
  maxHeight: number
}

export const MetricsPanel = ({ thread, width, maxHeight }: Props): React.ReactElement => {
  const status = useSessionStore((s) => s.status)
  const nowMs = useSessionStore((s) => s.wallClockMs)

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
  const protocolNotes = useSessionStore((s) => s.protocolNotes)
  const memoryEnabled = useSessionStore((s) => s.memoryEnabled)
  const sessionMemoryMode = useSessionStore((s) => s.sessionMemoryMode)
  const skillsEnabled = useSessionStore((s) => s.skillsEnabled)
  const harnessEnabled = useSessionStore((s) => s.harnessEnabled)
  const cliToolsEnabled = useSessionStore((s) => s.cliToolsEnabled)
  const cliToolsCount = useSessionStore((s) => s.cliToolsCount)
  const mcpServerRows = useSessionStore((s) => s.mcpServerRows)
  const mcpServerNames = useSessionStore((s) => s.mcpServerNames)
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

  const memoryLabel = useMemo(() => {
    if (sessionMemoryMode != null && sessionMemoryMode !== '') {
      if (sessionMemoryMode === 'none') return '✗ none'
      if (sessionMemoryMode === 'off') return '✓ in-memory'
      return `✓ ${sessionMemoryMode}`
    }
    if (memoryEnabled === true) return '✓ ON'
    if (memoryEnabled === false) return '✗ OFF'
    return '—'
  }, [sessionMemoryMode, memoryEnabled])

  const memoryColor = useMemo(() => {
    if (
      sessionMemoryMode === 'sqlite' ||
      sessionMemoryMode === 'in-memory' ||
      sessionMemoryMode === 'off' ||
      memoryEnabled === true
    ) {
      return 'green' as const
    }
    if (sessionMemoryMode === 'none' || memoryEnabled === false) return 'red' as const
    return 'gray' as const
  }, [sessionMemoryMode, memoryEnabled])

  const bodyLines = useMemo(() => {
    const lines: React.ReactElement[] = []

    lines.push(
      <Text key="identity-h" bold color="white">
        Identity
      </Text>,
    )
    lines.push(
      <Text key="session" wrap="truncate-end">
        <Text color="gray">session </Text>
        <Text color="white">{sid}</Text>
      </Text>,
    )
    lines.push(
      <Text key="thread" wrap="truncate-end">
        <Text color="gray">thread </Text>
        <Text color="white">{th}</Text>
      </Text>,
    )
    lines.push(
      <Text key="times" wrap="truncate-end">
        <Text color="gray">started </Text>
        <Text color="white">{fmtTime(sessionStartedAt)}</Text>
        <Text color="gray"> · updated </Text>
        <Text color="white">{fmtTime(sessionUpdatedAt)}</Text>
      </Text>,
    )

    lines.push(spacer('sp-features'))
    lines.push(
      <Text key="features-h" bold color="white">
        Features
      </Text>,
    )
    lines.push(
      <Text key="memory" wrap="truncate-end">
        <Text color="gray">memory </Text>
        <Text color={memoryColor}>{memoryLabel}</Text>
      </Text>,
    )
    lines.push(
      <Text key="skills" wrap="truncate-end">
        <Text color="gray">skills </Text>
        <Text color={skillsEnabled === true ? 'green' : skillsEnabled === false ? 'red' : 'gray'}>
          {skillsEnabled === true ? '✓ ON (LT store)' : skillsEnabled === false ? '✗ OFF' : '—'}
        </Text>
      </Text>,
    )
    lines.push(
      <Text key="cli" wrap="truncate-end">
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
      </Text>,
    )
    lines.push(
      <Text key="harness" wrap="truncate-end">
        <Text color="gray">harness </Text>
        <Text color={harnessEnabled === true ? 'green' : harnessEnabled === false ? 'red' : 'gray'}>
          {harnessEnabled === true ? '✓ ON' : harnessEnabled === false ? '✗ OFF' : '—'}
        </Text>
      </Text>,
    )
    lines.push(
      <Text key="mcp" wrap="truncate-end">
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
      </Text>,
    )

    lines.push(spacer('sp-activity'))
    lines.push(
      <Text key="activity-h" bold color="white">
        Activity
      </Text>,
    )
    lines.push(
      <Text key="activity" wrap="truncate-end">
        <Text color="gray">uptime </Text>
        <Text color="yellow">{sessionOpenedAtMs ? fmtDuration(uptimeMs) : '—'}</Text>
        <Text color="gray"> · turns </Text>
        <Text color="yellow">{turnCount}</Text>
        <Text color="gray"> · </Text>
        <Badge color={RUN_STATUS_BADGE_COLOR[status as RunStatus] ?? 'gray'}>{status}</Badge>
      </Text>,
    )

    lines.push(spacer('sp-tokens'))
    lines.push(
      <Text key="tokens-h" bold color="white">
        Tokens
      </Text>,
    )
    lines.push(
      <Text key="tokens-sess" wrap="truncate-end">
        <Text color="gray">session </Text>
        <Text color="green">{fmtTokens(totalIn)}↑</Text>
        <Text color="gray"> </Text>
        <Text color="blue">{fmtTokens(totalOut)}↓</Text>
        <Text color="gray" dimColor>
          {' '}
          ({totalIn + totalOut} Σ)
        </Text>
      </Text>,
    )
    if (activeTurn) {
      lines.push(
        <Text key="tokens-turn" wrap="truncate-end">
          <Text color="gray">this turn </Text>
          <Text color="green">{fmtTokens(turnIn)}↑</Text>
          <Text color="gray"> </Text>
          <Text color="blue">{fmtTokens(turnOut)}↓</Text>
        </Text>,
      )
    }
    if (completedTurns.length > 0) {
      lines.push(
        <Text key="tokens-last" color="gray" dimColor wrap="truncate-end">
          last answer ·{' '}
          {completedTurns.at(-1)?.tokens != null ? `${completedTurns.at(-1)!.tokens} tok` : '—'}
        </Text>,
      )
    }

    lines.push(spacer('sp-cost'))
    lines.push(
      <Text key="cost-h" bold color="white">
        Cost
      </Text>,
    )
    lines.push(
      <Text key="cost" color={totalCostUsd > 0 ? 'yellow' : 'gray'} dimColor={totalCostUsd <= 0} wrap="truncate-end">
        {fmtUsd(totalCostUsd)}
        {totalCostUsd > 0 ? ' (session)' : ''}
      </Text>,
    )

    if (phaseRows.length > 0) {
      lines.push(spacer('sp-phase'))
      lines.push(
        <Text key="phase-h" bold color="white">
          By phase
        </Text>,
      )
      for (const [phase, v] of phaseRows) {
        lines.push(
          <Text key={`phase-${phase}`} wrap="truncate-end">
            <Text color="magenta">{truncate(phase, 14).padEnd(14)}</Text>
            <Text color="green">{fmtTokens(v.input)}↑</Text>
            <Text color="gray"> </Text>
            <Text color="blue">{fmtTokens(v.output)}↓</Text>
          </Text>,
        )
      }
    }

    if (mcpServerRows.length > 0 || mcpServerNames.length > 0) {
      lines.push(spacer('sp-mcp'))
      lines.push(
        <Text key="mcp-h" bold color="white">
          MCP
        </Text>,
      )
      if (mcpServerRows.length > 0) {
        mcpServerRows.forEach((r, i) => {
          lines.push(
            <Text key={`mcp-${r.name}-${i}`} wrap="truncate-end">
              <Text color={r.ok ? 'green' : 'red'}>{r.ok ? '● ' : '○ '}</Text>
              <Text color="cyan">{truncate(r.name, 18)}</Text>
              <Text color="gray">
                {r.ok ? ` · ${r.toolCount} tools` : ` · ${truncate(String(r.error ?? 'error'), innerW - 22)}`}
              </Text>
            </Text>,
          )
        })
      } else {
        mcpServerNames.forEach((n, i) => {
          lines.push(
            <Text key={`mcp-pend-${i}`} wrap="truncate-end">
              <Text color="yellow">○ </Text>
              <Text color="cyan">{truncate(n, 18)}</Text>
              <Text color="gray" dimColor>
                {' '}
                · pending (first message)
              </Text>
            </Text>,
          )
        })
      }
    }

    if (filesUpdated.length > 0) {
      lines.push(spacer('sp-files'))
      lines.push(
        <Text key="files-h" bold color="white">
          Files updated
        </Text>,
      )
      filesUpdated.slice(-6).forEach((f, i) => {
        lines.push(
          <Text key={`file-${i}`} color="green" dimColor wrap="truncate-end">
            ✓ {truncate(f, innerW - 2)}
          </Text>,
        )
      })
    }

    if (autoApprovedTools.length > 0) {
      lines.push(spacer('sp-auto'))
      lines.push(
        <Text key="auto-h" bold color="white">
          Auto-approved
        </Text>,
      )
      lines.push(
        <Text key="auto-list" color="gray" dimColor wrap="truncate-end">
          {autoApprovedTools.join(', ')}
        </Text>,
      )
    }

    lines.push(spacer('sp-tools'))
    lines.push(
      <Text key="tools-h" bold color="white">
        Tools (recent)
      </Text>,
    )
    if (toolRows.length === 0) {
      lines.push(
        <Text key="tools-empty" color="gray" dimColor>
          —
        </Text>,
      )
    } else {
      for (const { turnLabel, tc } of toolRows) {
        lines.push(
          <Text key={tc.id} wrap="truncate-end">
            <Text color="gray">T{turnLabel} </Text>
            <Badge color={TOOL_STATUS_BADGE_COLOR[tc.status]}>{tc.status}</Badge>
            <Text bold> {truncate(tc.tool, 18)}</Text>
            {tc.durationMs !== undefined ? (
              <Text color="gray" dimColor>
                {' '}
                {fmtDuration(tc.durationMs)}
              </Text>
            ) : tc.status === 'pending' ? (
              <Text color="gray" dimColor>
                {' '}
                …
              </Text>
            ) : null}
          </Text>,
        )
      }
    }

    if (protocolNotes.length > 0) {
      lines.push(spacer('sp-wire'))
      lines.push(
        <Text key="wire-h" bold color="white">
          Wire notes
        </Text>,
      )
      protocolNotes.slice(-8).forEach((line, i) => {
        lines.push(
          <Text key={`wire-${i}-${line.slice(0, 12)}`} color="gray" dimColor wrap="truncate-end">
            {truncate(line, innerW)}
          </Text>,
        )
      })
    }

    return lines
  }, [
    activeTurn,
    autoApprovedTools,
    cliToolsCount,
    cliToolsEnabled,
    completedTurns,
    filesUpdated,
    harnessEnabled,
    innerW,
    mcpRollup,
    mcpServerNames,
    mcpServerRows,
    memoryColor,
    memoryLabel,
    phaseRows,
    protocolNotes,
    sessionOpenedAtMs,
    sessionStartedAt,
    sessionUpdatedAt,
    sid,
    skillsEnabled,
    status,
    th,
    toolRows,
    totalCostUsd,
    totalIn,
    totalOut,
    turnCount,
    turnIn,
    turnOut,
    uptimeMs,
  ])

  /** Title (2) + border/pad (2) + optional scroll hint (1). */
  const scrollBodyLines = Math.max(4, maxHeight - 5)

  return (
    <Box
      flexDirection="column"
      width={width}
      height={maxHeight}
      flexShrink={0}
      borderStyle="round"
      borderColor="cyan"
      paddingX={1}
      paddingY={1}
    >
      <Text bold color="cyan">
        Session
      </Text>
      <Text color="gray" dimColor wrap="truncate-end">
        {runtimeVersion ? `rt ${runtimeVersion}` : ' '}
        {model ? ` · ${truncate(model, innerW - 12)}` : ''}
      </Text>

      <ScrollableColumn
        maxLines={scrollBodyLines}
        lines={bodyLines}
        pinToBottomOnGrow
        allowBracketScroll={false}
      />
    </Box>
  )
}
