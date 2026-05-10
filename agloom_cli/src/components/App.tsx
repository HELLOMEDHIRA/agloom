/**
 * App — root Ink component.
 *
 * Layout (top → bottom):
 *   Header      — model / pattern / token metadata
 *   <Static>    — completed conversation turns (written once, never re-rendered)
 *   ActiveTurn  — current in-flight turn (re-renders on every token)
 *   HITLPrompt  — shown only when a HITL gate is pending (replaces InputBar)
 *   ErrorBanner — transient / fatal error messages
 *   InputBar    — primary user input
 *   StatusBar   — status, thread, session, keyboard hints
 *   MetricsPanel — optional right column: session id, uptime, turns, tokens, phase rollup, tools
 *
 * Design constraints:
 *   • Python runtime NEVER emits formatted terminal text — only AGP events.
 *   • All state mutations go through `useSessionStore.dispatch`.
 *   • Completed turns are Static so the terminal doesn't flicker on token deltas.
 */

import React, { useState } from 'react'
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

interface AppProps {
  bridge: AGPBridge
  initialThread: string
  /** Optional session id for resumption */
  session?: string
  /** Show diagnostic log pane */
  showDiag?: boolean
}

export function App({ bridge, initialThread, session: _session, showDiag = false }: AppProps): React.ReactElement {
  const { exit } = useApp()

  // Wire the bridge into the store
  useAGPStream(bridge)

  const completedTurns = useSessionStore((s) => s.completedTurns)
  const hitlQueue = useSessionStore((s) => s.hitlQueue)
  const status = useSessionStore((s) => s.status)
  const errorMessage = useSessionStore((s) => s.errorMessage)
  const diagnostics = useSessionStore((s) => s.diagnostics)
  const reset = useSessionStore((s) => s.reset)
  const clearError = useSessionStore((s) => s.clearError)

  const [thread] = useState(initialThread)
  const [input, setInput] = useState('')
  const [diagOpen, setDiagOpen] = useState(showDiag)
  const [metricsSidebarOpen, setMetricsSidebarOpen] = useState(true)

  const { columns } = useWindowSize()
  const termWidth = columns ?? 80

  const SIDEBAR_WIDTH = 38
  /** Minimum terminal width before we split chat + metrics (≈44 cols chat + sidebar + gap). */
  const SPLIT_MIN_TERM_WIDTH = 83
  const showMetricsSidebar = metricsSidebarOpen && termWidth >= SPLIT_MIN_TERM_WIDTH
  const mainColumnWidth = showMetricsSidebar ? termWidth - SIDEBAR_WIDTH - 1 : termWidth

  // ── Global keyboard shortcuts ──────────────────────────────────────────────
  useInput((char, key) => {
    if (key.ctrl && char === 'c') {
      bridge.shutdown()
      setTimeout(() => exit(), 600)
      return
    }
    if (key.ctrl && char === 'x') {
      bridge.cancel(thread)
      return
    }
  })

  // ── Input submit handler ───────────────────────────────────────────────────
  const handleSubmit = (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return

    if (trimmed.startsWith('/')) {
      handleSlashCommand(trimmed)
      setInput('')
      return
    }

    bridge.invoke(trimmed, thread)
    setInput('')
  }

  const handleSlashCommand = (cmd: string) => {
    const [command, ...rest] = cmd.split(/\s+/)

    switch (command) {
      case '/help':
        // Help is rendered inline — just clear input, the hints are shown by InputBar
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
        break

      case '/diag':
        setDiagOpen((prev) => !prev)
        break

      case '/stats':
        setMetricsSidebarOpen((prev) => !prev)
        break

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
        const model = useSessionStore.getState().model
        // Will show up in the next render cycle naturally via header
        void model
        break
      }

      default:
        break
    }

    clearError()
  }

  // ── Exited state ───────────────────────────────────────────────────────────
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
        {/* Top metadata bar */}
        <Header layoutWidth={mainColumnWidth} />

        {/* Completed turns — Static: written once, never diff'd again */}
        <Static items={completedTurns}>
          {(turn) => <CompletedTurnCard key={turn.id} turn={turn} />}
        </Static>

        {/* Active streaming turn */}
        <ActiveTurn />

        {/* ── HITL gate (replaces InputBar) ── */}
        {status === 'hitl' && hitlQueue[0] !== undefined && (
          <HITLPrompt request={hitlQueue[0]} bridge={bridge} />
        )}

        {/* Fatal error banner */}
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

        {/* Diagnostic log (toggled with /diag) */}
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

        {/* Normal input bar (hidden when HITL is active) */}
        {status !== 'hitl' && (
          <InputBar value={input} onChange={setInput} onSubmit={handleSubmit} />
        )}

        {/* Bottom status bar */}
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
