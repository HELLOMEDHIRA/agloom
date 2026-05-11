/** Root Ink layout: AGP-driven state via `useSessionStore.dispatch`; completed turns use `<Static>`. */

import React, { useMemo, useState } from 'react'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { Box, Text, Static, useApp, useInput, useWindowSize } from 'ink'
import { Header } from './Header.js'
import { CompletedTurnCard } from './CompletedTurnCard.js'
import { ActiveTurn } from './ActiveTurn.js'
import { HITLPrompt } from './HITLPrompt.js'
import { InputBar } from './InputBar.js'
import { StatusBar } from './StatusBar.js'
import { MetricsPanel } from './MetricsPanel.js'
import { useAGPStream } from '../hooks/useAGPStream.js'
import { useSessionStore } from '../store/session.js'
import type { AGPBridge } from '../runtime/bridge.js'
import { SLASH_HELP_LINES } from '../utils/slashCommands.js'
import { appendHistory, defaultHistoryPath, loadHistory } from '../utils/promptHistory.js'
import { splitPastedMultilineWhenSingleLineMode } from '../utils/pasteCompose.js'

interface AppProps {
  bridge: AGPBridge
  initialThread: string
  /** Show diagnostic log pane */
  showDiag?: boolean
  /** Multi-line compose: Enter adds line; blank Enter sends buffer. */
  multiline?: boolean
  /** Prompt history JSON path (default ~/.agloom/history.json). */
  historyFile?: string
}

export const App = ({
  bridge,
  initialThread,
  showDiag = false,
  multiline = false,
  historyFile,
}: AppProps): React.ReactElement => {
  const { exit } = useApp()
  useAGPStream(bridge)

  const completedTurns = useSessionStore((s) => s.completedTurns)
  const hitlQueue = useSessionStore((s) => s.hitlQueue)
  const status = useSessionStore((s) => s.status)
  const errorMessage = useSessionStore((s) => s.errorMessage)
  const diagnostics = useSessionStore((s) => s.diagnostics)
  const reset = useSessionStore((s) => s.reset)
  const clearError = useSessionStore((s) => s.clearError)
  const appendProtocolNote = useSessionStore((s) => s.appendProtocolNote)

  const [thread] = useState(initialThread)
  const [input, setInput] = useState('')
  const [diagOpen, setDiagOpen] = useState(showDiag)
  const [metricsSidebarOpen, setMetricsSidebarOpen] = useState(true)
  const [slashHelpOpen, setSlashHelpOpen] = useState(false)
  const [pendingLines, setPendingLines] = useState<string[]>([])
  const [pasteCompose, setPasteCompose] = useState(false)
  const histPath = historyFile ?? defaultHistoryPath()
  const [histRefresh, setHistRefresh] = useState(0)
  const histLines = useMemo(() => {
    void histRefresh
    return loadHistory(histPath)
  }, [histPath, histRefresh])
  const [histIdx, setHistIdx] = useState(0)

  const multilineOpt =
    multiline ||
    (typeof process.env['AGLOOM_MULTILINE'] === 'string' &&
      ['1', 'true', 'yes'].includes(process.env['AGLOOM_MULTILINE'].toLowerCase()))
  /** Multiline compose: explicit flag/env, or auto after pasting text with newlines. */
  const ml = multilineOpt || pasteCompose

  const { columns } = useWindowSize()
  const termWidth = columns ?? 80

  const SIDEBAR_WIDTH = 38
  /** Minimum terminal width before we split chat + metrics (≈44 cols chat + sidebar + gap). */
  const SPLIT_MIN_TERM_WIDTH = 83
  const showMetricsSidebar = metricsSidebarOpen && termWidth >= SPLIT_MIN_TERM_WIDTH
  const mainColumnWidth = showMetricsSidebar ? termWidth - SIDEBAR_WIDTH - 1 : termWidth

  useInput((char, key) => {
    if (slashHelpOpen) {
      if (key.escape || char === 'q') setSlashHelpOpen(false)
      return
    }
    if (key.ctrl && char === 'c') {
      bridge.shutdown()
      setTimeout(() => exit(), 600)
      return
    }
    if (key.ctrl && char === 'x') {
      bridge.cancel(thread)
      return
    }
    if (key.ctrl && char === 't') {
      useSessionStore.getState().toggleActiveTurnToolExpandBulk()
      appendProtocolNote('Tools: toggled expand/collapse for current turn (Ctrl+T)')
      return
    }
    if (char === 't' && !key.ctrl && input === '' && !slashHelpOpen) {
      useSessionStore.getState().toggleActiveTurnToolExpandBulk()
      appendProtocolNote('Tools: toggled expand/collapse for current turn (t)')
      return
    }
  })

  const recallPrev = (): void => {
    if (histLines.length === 0) return
    const i = (histIdx - 1 + histLines.length) % histLines.length
    setHistIdx(i)
    setInput(histLines[i] ?? '')
  }

  const recallNext = (): void => {
    if (histLines.length === 0) return
    const i = (histIdx + 1) % histLines.length
    setHistIdx(i)
    setInput(histLines[i] ?? '')
  }

  const handleInputChange = (v: string): void => {
    const pasted = splitPastedMultilineWhenSingleLineMode(multilineOpt, v)
    if (pasted) {
      setPasteCompose(true)
      if (pasted.headLines.length > 0) {
        setPendingLines((p) => [...p, ...pasted.headLines])
      }
      setInput(pasted.inputTail)
      return
    }
    setInput(v)
  }

  const handleSubmit = (text: string) => {
    const trimmed = text.trim()
    if (trimmed.startsWith('/')) {
      handleSlashCommand(trimmed)
      setInput('')
      setPendingLines([])
      setPasteCompose(false)
      return
    }

    if (ml) {
      if (text === '' && pendingLines.length > 0) {
        const body = pendingLines.join('\n')
        bridge.invoke(body, thread)
        appendHistory(histPath, body)
        setHistRefresh((n) => n + 1)
        setPendingLines([])
        setPasteCompose(false)
        setInput('')
        return
      }
      if (text !== '') {
        setPendingLines((p) => [...p, text])
        setInput('')
        return
      }
      return
    }

    if (!trimmed) return
    bridge.invoke(trimmed, thread)
    appendHistory(histPath, trimmed)
    setHistRefresh((n) => n + 1)
    setPasteCompose(false)
    setInput('')
  }

  const handleSlashCommand = (cmd: string) => {
    const [command, ...rest] = cmd.split(/\s+/)

    switch (command) {
      case '/help':
        setSlashHelpOpen((v) => !v)
        break

      case '/exit':
      case '/quit':
        bridge.shutdown()
        setTimeout(() => exit(), 600)
        break

      case '/cancel':
        bridge.cancel(thread)
        break

      case '/clear':
        reset()
        setPendingLines([])
        setPasteCompose(false)
        break

      case '/save': {
        const rawPath = rest.join(' ').trim()
        if (!rawPath) {
          appendProtocolNote('/save · usage: /save <path.md>')
          break
        }
        const turns = useSessionStore.getState().completedTurns
        const md = turns
          .map(
            (t) =>
              `### User\n\n${t.userMessage}\n\n### Assistant\n\n${t.assistantMessage}\n`,
          )
          .join('\n---\n\n')
        const target = resolve(rawPath)
        try {
          mkdirSync(dirname(target), { recursive: true })
          writeFileSync(target, `# agloom transcript\n\n${md}`, 'utf8')
          appendProtocolNote(`/save · wrote ${turns.length} turns → ${target}`)
        } catch (e) {
          appendProtocolNote(`/save · ${e instanceof Error ? e.message : String(e)}`)
        }
        break
      }

      case '/diag':
        setDiagOpen((prev) => !prev)
        break

      case '/stats':
        setMetricsSidebarOpen((prev) => !prev)
        break

      case '/tools': {
        useSessionStore.getState().toggleActiveTurnToolExpandBulk()
        appendProtocolNote('/tools · toggled expand/collapse for current turn (same as t / Ctrl+T)')
        break
      }

      case '/budget': {
        const sub = rest[0]?.toLowerCase()
        if (sub !== 'raise') {
          appendProtocolNote('/budget raise --tokens N  |  /budget raise --usd N  |  /budget raise N (tokens)')
          break
        }
        let tok: number | undefined
        let usd: number | undefined
        const tail = rest.slice(1)
        for (let i = 0; i < tail.length; i++) {
          const a = tail[i]?.toLowerCase()
          if (a === '--tokens' || a === '-t') {
            const n = parseInt(tail[++i] ?? '', 10)
            if (!Number.isNaN(n) && n > 0) tok = n
          } else if (a === '--usd' || a === '-u' || a === '--cost') {
            const n = parseFloat(tail[++i] ?? '')
            if (!Number.isNaN(n) && n > 0) usd = n
          } else if (tail[i] && /^\d+(\.\d+)?$/.test(tail[i]!) && tok === undefined && usd === undefined) {
            if (tail[i]!.includes('.')) usd = parseFloat(tail[i]!)
            else tok = parseInt(tail[i]!, 10)
          }
        }
        if (tok === undefined && usd === undefined) {
          appendProtocolNote('/budget raise · need --tokens N and/or --usd N (or one bare number = tokens)')
          break
        }
        bridge.configSet({
          ...(tok !== undefined ? { budget_token_limit: tok } : {}),
          ...(usd !== undefined ? { budget_cost_usd_limit: usd } : {}),
        })
        useSessionStore.setState({ budgetUi: 'ok' })
        appendProtocolNote(
          `/budget raise · sent command.config.set${tok != null ? ` · tokens≤${tok}` : ''}${usd != null ? ` · usd≤${usd}` : ''}`,
        )
        break
      }

      case '/feedback': {
        const [ratingStr, ...commentParts] = rest
        const rating = parseInt(ratingStr ?? '', 10)
        if (!isNaN(rating) && rating >= 1 && rating <= 5) {
          const comment = commentParts.join(' ') || undefined
          const lastTurn = useSessionStore.getState().completedTurns.at(-1)
          if (lastTurn?.runId) {
            bridge.feedback(lastTurn.runId, String(rating), comment)
          }
        }
        break
      }

      case '/model': {
        const st = useSessionStore.getState()
        const model = st.model ?? '—'
        const nTools = st.toolNames?.length
        appendProtocolNote(`/model · ${model}${nTools != null ? ` · ${nTools} tools` : ''}`)
        break
      }

      case '/memory': {
        const sub = rest[0]?.toLowerCase()
        if (sub === 'clear') bridge.memoryClear(thread)
        break
      }

      case '/cost': {
        const st = useSessionStore.getState()
        const lines = st.metricsHistory.slice(-16).map((m) => {
          const ph = m.phase ? `${m.phase}` : '—'
          const w = m.workerId ? ` ${m.workerId}` : ''
          return `  · ${ph}${w}: ↑${m.input} ↓${m.output}${m.model ? ` (${m.model})` : ''}`
        })
        appendProtocolNote(
          `/cost · session ↑${st.totalInputTokens} ↓${st.totalOutputTokens} tok · $${st.totalCostUsd.toFixed(4)}`,
        )
        for (const ln of lines) appendProtocolNote(ln)
        break
      }

      case '/pattern': {
        const p = rest.join(' ').trim()
        if (p) bridge.configSet({ pattern: p })
        break
      }

      case '/temperature': {
        const t = parseFloat(rest[0] ?? '')
        if (!Number.isNaN(t)) bridge.configSet({ temperature: t })
        break
      }

      case '/system': {
        const text = rest.join(' ').trim()
        if (text) bridge.configSet({ system_prompt: text })
        break
      }

      case '/session': {
        const sub = rest[0]?.toLowerCase()
        if (sub === 'list') bridge.sessionList()
        break
      }

      default:
        break
    }

    clearError()
  }

  if (status === 'exited') {
    return (
      <Box flexDirection="column">
        <Text color="yellow">● Session ended. Press Ctrl+C to exit.</Text>
      </Box>
    )
  }

  return (
    <Box flexDirection="row" width={termWidth}>
      <Box flexDirection="column" width={mainColumnWidth}>
        <Header layoutWidth={mainColumnWidth} />

        {slashHelpOpen && (
          <Box
            flexDirection="column"
            borderStyle="round"
            borderColor="cyan"
            paddingX={1}
            marginX={1}
            marginBottom={0}
          >
            {SLASH_HELP_LINES.map((line, i) => (
              <Text key={i} color={line.startsWith('  ') || line === '' ? 'gray' : 'white'}>
                {line || ' '}
              </Text>
            ))}
            <Text dimColor color="gray">
              Esc or q — close
            </Text>
          </Box>
        )}

        <Static items={completedTurns}>
          {(turn) => <CompletedTurnCard key={turn.id} turn={turn} />}
        </Static>

        <ActiveTurn />

        {status === 'hitl' && hitlQueue[0] !== undefined && (
          <HITLPrompt request={hitlQueue[0]} bridge={bridge} />
        )}

        {status === 'error' && errorMessage && (
          <Box
            borderStyle="round"
            borderColor="red"
            paddingX={1}
            marginX={1}
            marginBottom={0}
          >
            <Text color="red" bold>
              ✗ Fatal:{' '}
            </Text>
            <Text color="red">{errorMessage}</Text>
          </Box>
        )}

        {diagOpen && diagnostics.length > 0 && (
          <Box
            flexDirection="column"
            borderStyle="single"
            borderColor="gray"
            paddingX={1}
            height={8}
            marginX={1}
          >
            <Text color="gray" bold dimColor>
              Diagnostics (/diag to close)
            </Text>
            {diagnostics.slice(-6).map((line, i) => (
              <Text key={i} color="gray" dimColor>
                {line}
              </Text>
            ))}
          </Box>
        )}

        {status !== 'hitl' && (
          <InputBar
            value={input}
            onChange={handleInputChange}
            onSubmit={handleSubmit}
            pendingLines={ml ? pendingLines : undefined}
            onRecallPrev={recallPrev}
            onRecallNext={recallNext}
          />
        )}

        <StatusBar thread={thread} layoutWidth={mainColumnWidth} />
      </Box>

      {showMetricsSidebar && (
        <Box marginLeft={1} flexDirection="column" width={SIDEBAR_WIDTH}>
          <MetricsPanel thread={thread} width={SIDEBAR_WIDTH} />
        </Box>
      )}
    </Box>
  )
}
