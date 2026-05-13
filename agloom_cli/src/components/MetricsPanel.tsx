/** MetricsPanel — right-hand session telemetry card (turns, uptime, tokens, tools).
 * Fed only from AGP-derived store state. LLM tokens are attributed per **phase** via `metric.tokens` (there is no per-tool token field on the wire today); tool rows show wall time from `tool.call.*` events.
 */

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

interface Props {
  thread: string
  /** Inner width (inside border). */
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

  const uptimeMs = sessionOpenedAtMs ? nowMs - sessionOpenedAtMs : 0
  const turnCount = completedTurns.length + (activeTurn ? 1 : 0)

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

  const sid = sessionId ? shortenMiddle(sessionId, Math.min(28, width - 2)) : '—'
  const th = shortenMiddle(thread, Math.min(24, width - 2))

  const innerW = Math.max(22, width - 2)

  return (
    <Box
      flexDirection="column"
      width={width}
      borderStyle="round"
      borderColor="cyan"
      paddingX={1}
    >
      <Text bold color="cyan">
        Session
      </Text>
      <Text color="gray" dimColor>
        {runtimeVersion ? `rt ${runtimeVersion}` : ' '}
        {model ? ` · ${truncate(model, innerW - 12)}` : ''}
      </Text>

      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">
          Identity
        </Text>
        <Text color="gray">session</Text>
        <Text color="white">{sid}</Text>
        <Text color="gray">thread</Text>
        <Text color="white">{th}</Text>
        {toolNames != null && toolNames.length > 0 && (
          <>
            <Text color="gray">tools ({toolNames.length})</Text>
            <Text color="gray" dimColor>
              {truncate(toolNames.join(', '), innerW)}
            </Text>
          </>
        )}
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">
          Activity
        </Text>
        <Text>
          <Text color="gray">uptime </Text>
          <Text color="yellow">{sessionOpenedAtMs ? fmtDuration(uptimeMs) : '—'}</Text>
        </Text>
        <Text>
          <Text color="gray">turns </Text>
          <Text color="yellow">{turnCount}</Text>
          <Text color="gray"> · </Text>
          <Text color="gray" dimColor>
            {status}
          </Text>
        </Text>
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">
          Tokens
        </Text>
        <Text>
          <Text color="gray">session </Text>
          <Text color="green">{fmtTokens(totalIn)}↑</Text>
          <Text color="gray"> </Text>
          <Text color="blue">{fmtTokens(totalOut)}↓</Text>
          <Text color="gray" dimColor>
            {' '}
            ({totalIn + totalOut} Σ)
          </Text>
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
            last answer ·{' '}
            {completedTurns.at(-1)?.tokens != null
              ? `${completedTurns.at(-1)!.tokens} tok`
              : '—'}
          </Text>
        )}
      </Box>

      {totalCostUsd > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">
            Cost
          </Text>
          <Text color="yellow">{fmtUsd(totalCostUsd)} est.</Text>
        </Box>
      )}

      {phaseRows.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">
            By phase
          </Text>
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

      <Box marginTop={1} flexDirection="column">
        <Text bold color="white">
          Tools (recent)
        </Text>
        {toolRows.length === 0 ? (
          <Text color="gray" dimColor>
            —
          </Text>
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
              </Text>
            </Box>
          ))
        )}
        <Text color="gray" dimColor>
          {truncate('Tool time = wall clock. LLM tokens roll up by phase.', innerW)}
        </Text>
      </Box>

      {protocolNotes.length > 0 && (
        <Box marginTop={1} flexDirection="column">
          <Text bold color="white">
            Wire notes
          </Text>
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
