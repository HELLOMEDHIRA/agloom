/** Browser WebSocket AGP client (same wire as CLI stdio bridge). */

import { createContext, useContext } from 'react'
import type { AGPCommand, AGPEvent, CommandConfigSetCmd, ConnectionStatus } from './types.js'
import { parseInboundAGPEventJSON } from './types.js'

type Listener<T> = (value: T) => void

const MAX_RECONNECT_MS = 30_000
const RECONNECT_JITTER_MS = 500

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
  onEvent(listener: Listener<AGPEvent>): () => void
  onStatus(listener: Listener<ConnectionStatus>): () => void
  onDiagnostic(listener: Listener<string>): () => void
}

export const createAGPClient = (
  url = `ws://${window.location.hostname}:8765`,
  reconnectMs = 2000,
): AGPClient => {
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let shouldReconnect = false
  const baseReconnectMs = reconnectMs
  let currentReconnectMs = reconnectMs
  let connectionStatus: ConnectionStatus = 'closed'

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

  const open = (): void => {
    setStatus('connecting')
    const socket = new WebSocket(url)
    ws = socket

    socket.onopen = () => {
      currentReconnectMs = baseReconnectMs
      setStatus('open')
      emitDiagnostic(`[agp] connected to ${url}`)
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
        reconnectTimer = setTimeout(() => open(), currentReconnectMs + jitter)
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
      ws?.close()
      ws = null
      setStatus('closed')
    },

    send(cmd: AGPCommand): void {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(cmd))
      }
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
