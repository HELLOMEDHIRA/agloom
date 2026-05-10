/**
 * AGPClient — browser WebSocket client for the agloom AGP runtime.
 *
 * Same AGP contract as the agloom CLI's AGPBridge but uses native browser
 * WebSocket instead of Node.js child_process.
 *
 * Connection URL: ws[s]://host:port  (agloom-runtime serve --transport=ws)
 * During development: /agp-ws is proxied by vite.config.ts.
 *
 * Usage:
 *   const client = new AGPClient('ws://localhost:8765')
 *   client.on('event', (evt) => store.dispatch(evt))
 *   client.connect()
 *
 *   client.invoke('What is agloom?', 't_abc')
 *   client.disconnect()
 */

import type { AGPCommand, AGPEvent, ConnectionStatus } from './types.js'
import { parseInboundAGPEventJSON } from './types.js'

type Listener<T> = (value: T) => void

const MAX_RECONNECT_MS = 30_000
const RECONNECT_JITTER_MS = 500

export class AGPClient {
  private ws: WebSocket | null = null
  private url: string
  private baseReconnectMs: number
  private currentReconnectMs: number
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private shouldReconnect = false

  private eventListeners = new Set<Listener<AGPEvent>>()
  private statusListeners = new Set<Listener<ConnectionStatus>>()
  private diagnosticListeners = new Set<Listener<string>>()

  public status: ConnectionStatus = 'closed'

  constructor(url = `ws://${window.location.hostname}:8765`, reconnectMs = 2000) {
    this.url = url
    this.baseReconnectMs = reconnectMs
    this.currentReconnectMs = reconnectMs
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  connect(): void {
    this.shouldReconnect = true
    this.currentReconnectMs = this.baseReconnectMs
    this._open()
  }

  disconnect(): void {
    this.shouldReconnect = false
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
    this._setStatus('closed')
  }

  private _open(): void {
    this._setStatus('connecting')
    const ws = new WebSocket(this.url)
    this.ws = ws

    ws.onopen = () => {
      this.currentReconnectMs = this.baseReconnectMs
      this._setStatus('open')
      this._emit('diagnostic', `[agp] connected to ${this.url}`)
    }

    ws.onmessage = (ev: MessageEvent<string>) => {
      try {
        const evt = parseInboundAGPEventJSON(JSON.parse(ev.data))
        this.eventListeners.forEach((l) => l(evt))
      } catch {
        this._emit('diagnostic', `[agp] non-JSON frame: ${String(ev.data).slice(0, 80)}`)
      }
    }

    ws.onerror = (ev: Event) => {
      const detail = ev instanceof ErrorEvent ? ev.message : 'unknown error'
      this._setStatus('error')
      this._emit('diagnostic', `[agp] WebSocket error on ${this.url}: ${detail}`)
    }

    ws.onclose = (ev: CloseEvent) => {
      this._emit('diagnostic', `[agp] closed (code=${ev.code} reason=${ev.reason || 'none'})`)
      if (this.shouldReconnect) {
        this._setStatus('connecting')
        const jitter = Math.floor(Math.random() * RECONNECT_JITTER_MS)
        this.reconnectTimer = setTimeout(() => this._open(), this.currentReconnectMs + jitter)
        // Exponential backoff capped at MAX_RECONNECT_MS
        this.currentReconnectMs = Math.min(this.currentReconnectMs * 2, MAX_RECONNECT_MS)
      } else {
        this._setStatus('closed')
      }
    }
  }

  // ── Commands ───────────────────────────────────────────────────────────────

  send(cmd: AGPCommand): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(cmd))
    }
  }

  invoke(prompt: string, thread?: string): void {
    this.send({ type: 'command.invoke', data: { prompt, thread } })
  }

  cancel(thread?: string): void {
    this.send({ type: 'command.cancel', data: { thread } })
  }

  hitlRespond(requestId: string, decision: string, text?: string): void {
    this.send({ type: 'command.hitl.respond', data: { request_id: requestId, decision, text } })
  }

  /** `rating` should be a string token: "positive", "negative", "neutral", or e.g. "5" */
  feedback(runId: string, rating: string, comment?: string): void {
    this.send({ type: 'command.feedback', data: { run_id: runId, rating, comment } })
  }

  snapshot(thread?: string, label?: string): void {
    this.send({ type: 'command.snapshot.request', data: { thread, label } })
  }

  // ── Pub/Sub ────────────────────────────────────────────────────────────────

  onEvent(listener: Listener<AGPEvent>): () => void {
    this.eventListeners.add(listener)
    return () => this.eventListeners.delete(listener)
  }

  onStatus(listener: Listener<ConnectionStatus>): () => void {
    this.statusListeners.add(listener)
    return () => this.statusListeners.delete(listener)
  }

  onDiagnostic(listener: Listener<string>): () => void {
    this.diagnosticListeners.add(listener)
    return () => this.diagnosticListeners.delete(listener)
  }

  private _setStatus(s: ConnectionStatus): void {
    this.status = s
    this.statusListeners.forEach((l) => l(s))
  }

  private _emit(channel: 'diagnostic', msg: string): void {
    if (channel === 'diagnostic') this.diagnosticListeners.forEach((l) => l(msg))
  }
}

// ── React context singleton ────────────────────────────────────────────────────
// Exposed so components can grab the client via useAGPClient() without prop drilling.

import { createContext, useContext } from 'react'

export const AGPClientContext = createContext<AGPClient | null>(null)

export function useAGPClient(): AGPClient {
  const client = useContext(AGPClientContext)
  if (!client) throw new Error('useAGPClient must be used inside <AGPProvider>')
  return client
}
