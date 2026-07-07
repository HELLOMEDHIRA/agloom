/** Browser WebSocket AGP client (same wire as CLI stdio bridge). */

import { createContext, useContext } from 'react'
import type { AGPCommand, AGPEvent, CommandConfigSetCmd, ConnectionStatus } from './types.js'
import { parseInboundAGPEventJSON } from './types.js'

type Listener<T> = (value: T) => void

const MAX_RECONNECT_MS = 30_000
const RECONNECT_JITTER_MS = 500
const MAX_OUTBOUND_QUEUE = 32

type QueuedCommand = { cmd: AGPCommand; droppedNote?: string }

export interface AGPClient {
  readonly status: ConnectionStatus
  connect(): void
  disconnect(): void
  send(cmd: AGPCommand): void
  invoke(prompt: string, thread?: string): void
  cancel(thread?: string): void
  hitlRespond(requestId: string, decision: string, text?: string): void
  feedback(runId: string, rating: string, comment?: string): void
  snapshot(thread?: string, label?: string): void
  attachFile(filename: string, contentBase64: string, thread?: string): void
  listProviders(): void
  configSet(data: CommandConfigSetCmd['data']): void
  memoryClear(thread?: string): void
  memoryPopLastTurn(thread?: string): void
  resume(thread: string, fromSeq?: number): void
  planPreview(prompt: string): void
  harnessGit(
    op: 'checkpoint' | 'diff' | 'status' | 'checkpoints' | 'revert_hint',
    data?: { name?: string; description?: string; path?: string; cached?: boolean },
  ): void
  onEvent(listener: Listener<AGPEvent>): () => void
  onStatus(listener: Listener<ConnectionStatus>): () => void
  onDiagnostic(listener: Listener<string>): () => void
}

export const createAGPClient = (
  url = `ws://${window.location.hostname}:8765`,
  reconnectMs = 2000,
  options?: {
    getResumeState?: () => { thread: string | null; fromSeq: number }
  },
): AGPClient => {
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let shouldReconnect = false
  const baseReconnectMs = reconnectMs
  let currentReconnectMs = reconnectMs
  let connectionStatus: ConnectionStatus = 'closed'
  let hasConnectedOnce = false
  const outboundQueue: QueuedCommand[] = []

  const eventListeners = new Set<Listener<AGPEvent>>()
  const statusListeners = new Set<Listener<ConnectionStatus>>()
  const diagnosticListeners = new Set<Listener<string>>()

  const emitDiagnostic = (msg: string) => {
    diagnosticListeners.forEach((l) => l(msg))
  }

  const setStatus = (s: ConnectionStatus) => {
    connectionStatus = s
    statusListeners.forEach((l) => l(s))
  }

  const flushOutboundQueue = (): void => {
    if (ws?.readyState !== WebSocket.OPEN) return
    while (outboundQueue.length > 0) {
      const item = outboundQueue.shift()!
      if (item.droppedNote) emitDiagnostic(item.droppedNote)
      ws.send(JSON.stringify(item.cmd))
    }
  }

  const enqueueOrSend = (cmd: AGPCommand): void => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(cmd))
      return
    }
    if (outboundQueue.length >= MAX_OUTBOUND_QUEUE) {
      const dropped = outboundQueue.shift()
      if (dropped) {
        outboundQueue.push({
          cmd,
          droppedNote: `[agp] outbound queue full; dropped oldest ${dropped.cmd.type}`,
        })
        return
      }
    }
    outboundQueue.push({ cmd })
    if (connectionStatus === 'connecting') {
      emitDiagnostic(`[agp] queued outbound ${cmd.type} while connecting`)
    } else {
      emitDiagnostic(`[agp] queued outbound ${cmd.type}: WebSocket not open (state=${ws?.readyState ?? 'none'})`)
    }
  }

  const open = (resumeAfterReconnect?: { thread: string; fromSeq: number }): void => {
    setStatus('connecting')
    const socket = new WebSocket(url)
    ws = socket

    socket.onopen = () => {
      currentReconnectMs = baseReconnectMs
      setStatus('open')
      emitDiagnostic(`[agp] connected to ${url}`)
      if (resumeAfterReconnect && resumeAfterReconnect.fromSeq > 0) {
        enqueueOrSend({
          type: 'command.session.resume',
          data: { thread: resumeAfterReconnect.thread, from_seq: resumeAfterReconnect.fromSeq },
        })
      }
      flushOutboundQueue()
      hasConnectedOnce = true
    }

    socket.onmessage = (ev: MessageEvent<string>) => {
      try {
        const evt = parseInboundAGPEventJSON(JSON.parse(ev.data))
        eventListeners.forEach((l) => l(evt))
      } catch {
        emitDiagnostic(`[agp] non-JSON frame: ${String(ev.data).slice(0, 80)}`)
      }
    }

    socket.onerror = (ev: Event) => {
      const detail = ev instanceof ErrorEvent ? ev.message : 'unknown error'
      setStatus('error')
      emitDiagnostic(`[agp] WebSocket error on ${url}: ${detail}`)
    }

    socket.onclose = (ev: CloseEvent) => {
      emitDiagnostic(`[agp] closed (code=${ev.code} reason=${ev.reason || 'none'})`)
      if (shouldReconnect) {
        setStatus('connecting')
        const jitter = Math.floor(Math.random() * RECONNECT_JITTER_MS)
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null
          const resumeState =
            hasConnectedOnce && options?.getResumeState
              ? options.getResumeState()
              : null
          if (resumeState?.thread && resumeState.fromSeq > 0) {
            open({ thread: resumeState.thread, fromSeq: resumeState.fromSeq })
          } else {
            open()
          }
        }, currentReconnectMs + jitter)
        currentReconnectMs = Math.min(currentReconnectMs * 2, MAX_RECONNECT_MS)
      } else {
        setStatus('closed')
      }
    }
  }

  const api: AGPClient = {
    get status() {
      return connectionStatus
    },

    connect(): void {
      shouldReconnect = true
      currentReconnectMs = baseReconnectMs
      open()
    },

    disconnect(): void {
      shouldReconnect = false
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      outboundQueue.length = 0
      ws?.close()
      ws = null
      setStatus('closed')
    },

    send(cmd: AGPCommand): void {
      enqueueOrSend(cmd)
    },

    invoke(prompt: string, thread?: string): void {
      api.send({ type: 'command.invoke', data: { prompt, thread } })
    },

    cancel(thread?: string): void {
      api.send({ type: 'command.cancel', data: { thread } })
    },

    hitlRespond(requestId: string, decision: string, text?: string): void {
      api.send({ type: 'command.hitl.respond', data: { request_id: requestId, decision, text } })
    },

    feedback(runId: string, rating: string, comment?: string): void {
      api.send({ type: 'command.feedback', data: { run_id: runId, rating, comment } })
    },

    snapshot(thread?: string, label?: string): void {
      api.send({ type: 'command.snapshot.request', data: { thread, label } })
    },

    attachFile(filename: string, contentBase64: string, thread?: string): void {
      api.send({
        type: 'command.attach.file',
        data: { filename, content_base64: contentBase64, thread },
      })
    },

    listProviders(): void {
      api.send({ type: 'command.providers.list', data: {} })
    },

    configSet(data: CommandConfigSetCmd['data']): void {
      api.send({ type: 'command.config.set', data })
    },

    memoryClear(thread?: string): void {
      api.send({ type: 'command.memory.clear', data: { thread } })
    },

    memoryPopLastTurn(thread?: string): void {
      api.send({ type: 'command.memory.pop_last_turn', data: { thread } })
    },

    resume(thread: string, fromSeq?: number): void {
      api.send({
        type: 'command.session.resume',
        data: { thread, from_seq: fromSeq ?? 0 },
      })
    },

    planPreview(prompt: string): void {
      api.send({ type: 'command.plan.preview', data: { prompt } })
    },

    harnessGit(op, data = {}): void {
      api.send({ type: 'command.harness.git', data: { op, ...data } })
    },

    onEvent(listener: Listener<AGPEvent>): () => void {
      eventListeners.add(listener)
      return () => eventListeners.delete(listener)
    },

    onStatus(listener: Listener<ConnectionStatus>): () => void {
      statusListeners.add(listener)
      return () => statusListeners.delete(listener)
    },

    onDiagnostic(listener: Listener<string>): () => void {
      diagnosticListeners.add(listener)
      return () => diagnosticListeners.delete(listener)
    },
  }

  return api
}

export const AGPClientContext = createContext<AGPClient | null>(null)

export const useAGPClient = (): AGPClient => {
  const client = useContext(AGPClientContext)
  if (!client) throw new Error('useAGPClient must be used inside <AGPProvider>')
  return client
}
