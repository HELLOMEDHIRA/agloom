/** Root terminal UI layout: AGP-driven state via `useSessionStore.dispatch`; completed turns render in the live tree (replay-safe). */

import React, { useEffect, useMemo, useState } from 'react'
import { dirname, isAbsolute, join, relative, resolve } from 'node:path'
import { Alert } from '@inkjs/ui'
import { Box, Text, useApp, useInput, useWindowSize } from 'ink'
import { Header } from './Header.js'
import { ActiveTurn } from './ActiveTurn.js'
import { HITLPrompt } from './HITLPrompt.js'
import { InputBar } from './InputBar.js'
import { StatusBar } from './StatusBar.js'
import { MetricsPanel } from './MetricsPanel.js'
import { ChatTranscript } from './ChatTranscript.js'
import { useAGPStream } from '../hooks/useAGPStream.js'
import { useSessionStore } from '../store/session.js'
import type { AGPBridge } from '../runtime/bridge.js'
import { SLASH_HELP_LINES } from '../utils/slashCommands.js'
import { appendHistory, defaultHistoryPath, loadHistory } from '../utils/promptHistory.js'
import { suggestFromHistory } from '../utils/fuzzySuggest.js'
import { splitPastedMultilineWhenSingleLineMode } from '../utils/pasteCompose.js'
import { resolveAgloomProjectRoot } from '../config.js'
import { persistUserSystemPromptToYaml } from '../yamlSystemPromptMigrate.js'

interface AppProps {
  bridge: AGPBridge
  initialThread: string
  /** Show diagnostic log pane */
  showDiag?: boolean
  /** Multi-line compose: Enter adds line; blank Enter sends buffer. */
  multiline?: boolean
  /** Prompt history JSON path (default ~/.agloom/history.json). */
  historyFile?: string
  /** When resuming, CLI ``--session`` id (shown until ``session.opened`` / ``session.resumed`` arrives). */
  cliSessionId?: string | null
}

export const App = ({
  bridge,
  initialThread,
  showDiag = false,
  multiline = true,
  historyFile,
  cliSessionId,
}: AppProps): React.ReactElement => {
  const { exit } = useApp()
  useAGPStream(bridge)

  useEffect(() => {
    if (!cliSessionId?.trim()) return
    const cur = useSessionStore.getState().sessionId
    if (!cur) {
      useSessionStore.setState({ sessionId: cliSessionId.trim() })
    }
  }, [cliSessionId])

  useEffect(() => {
    const tick = (): void => useSessionStore.getState().setWallClockMs(Date.now())
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])

  const completedTurns = useSessionStore((s) => s.completedTurns)
  const activeTurn = useSessionStore((s) => s.activeTurn)
  const outboundPrompt = useSessionStore((s) => s.outboundPrompt)
  const hitlQueue = useSessionStore((s) => s.hitlQueue)
  const status = useSessionStore((s) => s.status)
  const errorMessage = useSessionStore((s) => s.errorMessage)
  const diagnostics = useSessionStore((s) => s.diagnostics)
  const reset = useSessionStore((s) => s.reset)
  const clearError = useSessionStore((s) => s.clearError)
  const appendProtocolNote = useSessionStore((s) => s.appendProtocolNote)

  const activeThreadId = useSessionStore((s) => s.activeThreadId)
  const thread = activeThreadId ?? initialThread
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
  /** `null` = composing new input; otherwise index into `histLines`. */
  const [histIdx, setHistIdx] = useState<number | null>(null)

  useEffect(() => {
    setHistIdx(null)
  }, [histRefresh, histLines.length])

  const fuzzySuggestions = useMemo(
    () => (!input.startsWith('/') ? suggestFromHistory(input, histLines, 4) : []),
    [input, histLines],
  )

  const multilineOpt = multiline
  /** Multiline compose from ``agloom.yaml`` ``multiline`` (default on when omitted), or auto after pasting newlines when false. */
  const ml = multilineOpt || pasteCompose

  const { columns, rows } = useWindowSize()
  const termWidth = columns ?? 80
  /** Prefer Ink-reported rows; fall back to TTY rows so the composer stays at the physical bottom in narrow hosts. */
  const ttyRows =
    typeof process.stdout.rows === 'number' && process.stdout.rows > 4 ? process.stdout.rows : 24
  const termHeight = rows != null && rows > 6 ? rows : ttyRows

  const SIDEBAR_WIDTH = 44
  /** Minimum terminal width before we split chat + metrics (main ≈48 + sidebar + gap). */
  const SPLIT_MIN_TERM_WIDTH = 92
  const showMetricsSidebar = metricsSidebarOpen && termWidth >= SPLIT_MIN_TERM_WIDTH
  const mainColumnWidth = showMetricsSidebar ? termWidth - SIDEBAR_WIDTH - 1 : termWidth
  const setMainColumnWidth = useSessionStore((s) => s.setMainColumnWidth)

  useEffect(() => {
    setMainColumnWidth(mainColumnWidth)
  }, [mainColumnWidth, setMainColumnWidth])

  const headerRows = 3
  const statusRows = 2
  const inputRows = status !== 'hitl' ? 4 : 0
  const hitlRows = status === 'hitl' ? 7 : 0
  /** Pinned footer dock (status + composer / HITL) — reserved from the bottom of the terminal. */
  const footerRows = statusRows + (status === 'hitl' ? hitlRows : inputRows)
  /** Middle pane height (header + footer are outside this row). */
  const middleRowHeight = Math.max(10, termHeight - headerRows - footerRows)
  /** Rows inside the middle pane above the scrollable transcript (footer rows are not subtracted again). */
  const activeTurnRows = activeTurn ? 8 : 0
  const diagRows = diagOpen ? 9 : 0
  const slashRows = slashHelpOpen ? SLASH_HELP_LINES.length + 4 : 0
  const outboundRows = outboundPrompt && !activeTurn ? 2 : 0
  const middleOverhead =
    (slashHelpOpen ? slashRows : 0) +
    activeTurnRows +
    (diagOpen ? diagRows : 0) +
    outboundRows +
    1
  const chatScrollLines = Math.max(4, middleRowHeight - middleOverhead)

  useInput((char, key) => {
    if (slashHelpOpen) {
      if (key.escape || char === 'q') setSlashHelpOpen(false)
      return
    }
    if (key.escape && (input !== '' || pendingLines.length > 0)) {
      setInput('')
      setPendingLines([])
      setPasteCompose(false)
      return
    }
    if (key.ctrl && char === 'c') {
      bridge.shutdown()
      setTimeout(() => bridge.kill(), 150)
      setTimeout(() => exit(), 600)
      return
    }
    if (key.ctrl && char === 'x') {
      bridge.cancel(thread)
      return
    }
  })

  const recallPrev = (): void => {
    if (histLines.length === 0) return
    const i = histIdx === null ? histLines.length - 1 : Math.max(0, histIdx - 1)
    setHistIdx(i)
    setInput(histLines[i] ?? '')
  }

  const recallNext = (): void => {
    if (histLines.length === 0) return
    if (histIdx === null) return
    if (histIdx >= histLines.length - 1) {
      setHistIdx(null)
      setInput('')
      return
    }
    const i = histIdx + 1
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
        useSessionStore.setState({ outboundPrompt: body })
        bridge.invoke(body, thread)
        appendHistory(histPath, body)
        setHistRefresh((n) => n + 1)
        setHistIdx(null)
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
    useSessionStore.setState({ outboundPrompt: trimmed })
    bridge.invoke(trimmed, thread)
    appendHistory(histPath, trimmed)
    setHistRefresh((n) => n + 1)
    setHistIdx(null)
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

      case '/undo':
        bridge.memoryPopLastTurn(thread)
        appendProtocolNote('/undo · popping last turn from session memory')
        break

      case '/retry': {
        const st = useSessionStore.getState()
        if (st.status === 'running' || st.status === 'thinking' || st.status === 'hitl') {
          appendProtocolNote('/retry · wait for the current turn to finish (or /cancel)')
          break
        }
        const turns = st.completedTurns
        const last = turns[turns.length - 1]
        if (!last?.userMessage?.trim()) {
          appendProtocolNote('/retry · no completed turn to re-run')
          break
        }
        bridge.invoke(last.userMessage, thread)
        appendHistory(histPath, last.userMessage)
        appendProtocolNote(`/retry · re-running: "${last.userMessage}"`)
        setHistRefresh((n) => n + 1)
        break
      }

      case '/checkpoint': {
        const name = (rest[0] ?? 'cli').trim() || 'cli'
        const description = rest.slice(1).join(' ').trim() || 'CLI /checkpoint'
        bridge.harnessGit('checkpoint', { name, description })
        break
      }

      case '/diff': {
        let cached = false
        const pathParts: string[] = []
        for (const p of rest) {
          if (p === '--staged' || p === '--cached') cached = true
          else if (!p.startsWith('-')) pathParts.push(p)
        }
        bridge.harnessGit('diff', { path: pathParts.join(' ').trim(), cached })
        break
      }

      case '/hint':
        bridge.harnessGit('revert_hint', {})
        break

      case '/plan': {
        const goal = rest.join(' ').trim()
        if (!goal) {
          appendProtocolNote('/plan · usage: /plan <goal>')
          break
        }
        bridge.planPreview(goal)
        break
      }

      case '/git': {
        const sub = (rest[0] ?? 'status').toLowerCase()
        if (sub === 'status') bridge.harnessGit('status', {})
        else if (sub === 'checkpoints' || sub === 'list') bridge.harnessGit('checkpoints', {})
        else appendProtocolNote('/git · usage: /git status  |  /git checkpoints')
        break
      }

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
        const root = resolveAgloomProjectRoot(process.cwd())
        const target = isAbsolute(rawPath) ? resolve(rawPath) : resolve(root, rawPath)
        const rel = relative(root, target)
        if (rel.startsWith('..') || isAbsolute(rel)) {
          appendProtocolNote('/save · path must stay under project root')
          break
        }
        void (async () => {
          try {
            const { mkdir, writeFile } = await import('node:fs/promises')
            await mkdir(dirname(target), { recursive: true })
            await writeFile(target, `# agloom transcript\n\n${md}`, 'utf8')
            useSessionStore.getState().appendProtocolNote(`/save · wrote ${turns.length} turns → ${target}`)
          } catch (e) {
            useSessionStore.getState().appendProtocolNote(`/save · ${e instanceof Error ? e.message : String(e)}`)
          }
        })().catch((e) => {
          appendProtocolNote(`/save · unexpected: ${e instanceof Error ? e.message : String(e)}`)
        })
        break
      }

      case '/diag':
        setDiagOpen((prev) => !prev)
        break

      case '/stats': {
        const next = !metricsSidebarOpen
        setMetricsSidebarOpen(next)
        if (next && termWidth < SPLIT_MIN_TERM_WIDTH) {
          appendProtocolNote(
            `/stats · metrics sidebar needs terminal width ≥ ${SPLIT_MIN_TERM_WIDTH} cols (currently ${termWidth}); widen terminal or shrink font.`,
          )
        }
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

      case '/temperature': {
        const t = parseFloat(rest[0] ?? '')
        if (!Number.isNaN(t)) bridge.configSet({ temperature: t })
        break
      }

      case '/system': {
        const text = rest.join(' ').trim()
        if (text) {
          bridge.configSet({ system_prompt: text })
          const nestedYaml = join(resolveAgloomProjectRoot(process.cwd()), '.agloom', 'agloom.yaml')
          if (persistUserSystemPromptToYaml(nestedYaml, text)) {
            appendProtocolNote('Saved ai.system_prompt to .agloom/agloom.yaml (used on next restart)')
          }
        }
        break
      }

      case '/session': {
        const sub = rest[0]?.toLowerCase()
        if (sub === 'list') bridge.sessionList()
        break
      }

      default:
        appendProtocolNote(`Unknown command: ${command}. Try /help.`)
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
    <Box flexDirection="column" width={termWidth} height={termHeight}>
      <Box flexShrink={0} width={termWidth}>
        <Header layoutWidth={termWidth} />
      </Box>

      <Box
        flexDirection="row"
        flexGrow={1}
        minHeight={0}
        height={middleRowHeight}
        width={termWidth}
        alignItems="stretch"
      >
        <Box flexDirection="column" width={mainColumnWidth} flexGrow={1} minHeight={0}>
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

        <Box flexDirection="column" flexGrow={1} minHeight={0} marginX={1}>
          <ChatTranscript
            turns={completedTurns}
            width={mainColumnWidth}
            maxLines={chatScrollLines}
            allowBracketScroll={!showMetricsSidebar}
          />
        </Box>

        <ActiveTurn />

        {status === 'error' && errorMessage && (
          <Box marginX={1} marginBottom={0}>
            <Alert variant="error" title="Fatal">
              {errorMessage}
            </Alert>
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

        {outboundPrompt && !activeTurn && (
          <Box paddingX={1} flexDirection="row" flexWrap="wrap" flexShrink={0}>
            <Text>
              <Text color="cyan" bold>
                You
              </Text>
              <Text color="gray"> · </Text>
              <Text dimColor>
                {outboundPrompt}
              </Text>
            </Text>
          </Box>
        )}

        </Box>

      {showMetricsSidebar && (
        <Box
          marginLeft={1}
          flexDirection="column"
          width={SIDEBAR_WIDTH}
          height={middleRowHeight}
          minHeight={middleRowHeight}
          flexGrow={1}
          alignSelf="stretch"
          flexShrink={0}
        >
          <MetricsPanel thread={thread} width={SIDEBAR_WIDTH} maxHeight={middleRowHeight} />
        </Box>
      )}
      </Box>

      <Box flexShrink={0} flexDirection="row" width={termWidth}>
        <Box flexDirection="column" width={mainColumnWidth} flexShrink={0}>
          <StatusBar thread={thread} layoutWidth={mainColumnWidth} />
          {status === 'hitl' && hitlQueue[0] !== undefined ? (
            <HITLPrompt request={hitlQueue[0]} bridge={bridge} />
          ) : status !== 'hitl' ? (
            <InputBar
              value={input}
              onChange={handleInputChange}
              onSubmit={handleSubmit}
              pendingLines={ml ? pendingLines : undefined}
              onRecallPrev={recallPrev}
              onRecallNext={recallNext}
              suggestions={fuzzySuggestions}
              composerWidth={mainColumnWidth}
            />
          ) : null}
        </Box>
        {showMetricsSidebar ? <Box width={SIDEBAR_WIDTH + 1} flexShrink={0} /> : null}
      </Box>
    </Box>
  )
}
