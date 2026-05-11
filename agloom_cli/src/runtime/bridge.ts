/** Spawns `agloom-runtime serve` (stdio NDJSON); stderr → `diagnostic`. Runtime: `AGLOOM_RUNTIME` or `agloom-runtime` on PATH. */

import { execSync, spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { EventEmitter } from 'node:events'
import type { AGPEvent, AGPCommand, InvokeAttachment } from '../types/agp.js'
import { parseInboundAGPEventJSON } from '../types/agp.js'

export type BridgeStatus = 'starting' | 'ready' | 'error' | 'exited'

export interface BridgeExitInfo {
  code: number | null
  signal: string | null
}

/** Typed bridge API — created by {@link createAGPBridge}. */
export interface AGPBridge {
  readonly status: BridgeStatus
  readonly pid: number | undefined

  /**
   * Spawn the Python runtime. `extraArgs` are appended after `serve --transport=…`.
   *
   * **Transport:** this npm client only supports driving the runtime over **stdio**
   * (child stdin/stdout NDJSON). A remote `--transport=ws` server is not wired here;
   * use a WebSocket-capable client or run `agloom-runtime serve --transport=ws` separately.
   */
  start(extraArgs?: string[], options?: { transport?: 'stdio' }): void

  send(cmd: AGPCommand): void
  invoke(prompt: string, thread?: string, attachments?: InvokeAttachment[]): void
  cancel(thread?: string): void
  memoryClear(thread?: string): void
  configSet(data: {
    model_id?: string
    cli_tools?: Record<string, unknown>
    pattern?: string
    temperature?: number
    system_prompt?: string
    budget_token_limit?: number | null
    budget_cost_usd_limit?: number | null
  }): void
  sessionList(): void
  hitlRespond(requestId: string, decision: string, text?: string): void
  feedback(runId: string, rating: string, comment?: string): void
  snapshot(thread?: string, label?: string): void
  shutdown(): void
  kill(): void

  on(event: 'event', listener: (evt: AGPEvent) => void): AGPBridge
  on(event: 'diagnostic', listener: (line: string) => void): AGPBridge
  on(event: 'exit', listener: (info: BridgeExitInfo) => void): AGPBridge
  on(event: 'error', listener: (err: Error) => void): AGPBridge
  on(event: string, listener: (...args: unknown[]) => void): AGPBridge

  once(event: 'event', listener: (evt: AGPEvent) => void): AGPBridge
  once(event: 'diagnostic', listener: (line: string) => void): AGPBridge
  once(event: 'exit', listener: (info: BridgeExitInfo) => void): AGPBridge
  once(event: 'error', listener: (err: Error) => void): AGPBridge
  once(event: string, listener: (...args: unknown[]) => void): AGPBridge

  off(event: 'event', listener: (evt: AGPEvent) => void): AGPBridge
  off(event: 'diagnostic', listener: (line: string) => void): AGPBridge
  off(event: 'exit', listener: (info: BridgeExitInfo) => void): AGPBridge
  off(event: 'error', listener: (err: Error) => void): AGPBridge
  off(event: string, listener: (...args: unknown[]) => void): AGPBridge

  emit(event: 'event', evt: AGPEvent): boolean
  emit(event: 'diagnostic', line: string): boolean
  emit(event: 'exit', info: BridgeExitInfo): boolean
  emit(event: 'error', err: Error): boolean
  emit(event: string, ...args: unknown[]): boolean
}

/**
 * Create a stdio AGP bridge. Uses an internal `EventEmitter` for `on` / `once` / `emit`.
 */
export const createAGPBridge = (): AGPBridge => {
  const emitter = new EventEmitter()
  let proc: ChildProcess | null = null
  let buf = ''
  let status: BridgeStatus = 'starting'
  let pid: number | undefined

  const send = (cmd: AGPCommand): void => {
    if (!proc?.stdin?.writable) return
    proc.stdin.write(`${JSON.stringify(cmd)}\n`)
  }

  const start = (extraArgs: string[] = [], options?: { transport?: 'stdio' }): void => {
    const cmd = process.env['AGLOOM_RUNTIME'] ?? 'agloom-runtime'
    const transport = options?.transport ?? 'stdio'
    const args = ['serve', `--transport=${transport}`, ...extraArgs]

    proc = spawn(cmd, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env },
      shell: false,
      detached: process.platform !== 'win32',
    })

    pid = proc.pid

    proc.stdout?.setEncoding('utf8')
    proc.stdout?.on('data', (chunk: string) => {
      buf += chunk
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue
        try {
          const evt = parseInboundAGPEventJSON(JSON.parse(trimmed))
          emitter.emit('event', evt)
          if (evt.type === 'session.opened') status = 'ready'
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e)
          const preview = trimmed.length > 160 ? `${trimmed.slice(0, 157)}…` : trimmed
          emitter.emit('diagnostic', `[stdout] ${msg} | ${preview}`)
        }
      }
    })

    proc.stderr?.setEncoding('utf8')
    proc.stderr?.on('data', (chunk: string) => {
      for (const line of chunk.split('\n')) {
        const t = line.trim()
        if (t) emitter.emit('diagnostic', t)
      }
    })

    proc.on('exit', (code: number | null, signal: NodeJS.Signals | null) => {
      status = 'exited'
      emitter.emit('exit', { code, signal })
    })

    proc.on('error', (err: NodeJS.ErrnoException) => {
      const guidance =
        err.code === 'ENOENT'
          ? new Error(
              `Cannot find 'agloom-runtime'. Install agloom: pip install agloom\nOr set AGLOOM_RUNTIME=/path/to/python to point to your interpreter.`,
            )
          : err
      status = 'error'
      emitter.emit('error', guidance)
    })
  }

  const kill = (): void => {
    if (!proc) return
    const childPid = proc.pid
    if (childPid == null) {
      proc.kill('SIGTERM')
      return
    }
    if (process.platform === 'win32') {
      try {
        execSync(`taskkill /F /T /PID ${childPid}`, { stdio: 'ignore' })
      } catch {
        proc.kill('SIGTERM')
      }
    } else {
      try {
        process.kill(-childPid, 'SIGTERM')
      } catch {
        proc.kill('SIGTERM')
      }
    }
  }

  const bridgeRef: { current: AGPBridge | null } = { current: null }

  const bridge: AGPBridge = {
    get status(): BridgeStatus {
      return status
    },
    get pid(): number | undefined {
      return pid
    },
    start,
    send,
    invoke: (prompt: string, thread?: string, attachments?: InvokeAttachment[]) =>
      send({
        type: 'command.invoke',
        data: attachments?.length ? { prompt, thread, attachments } : { prompt, thread },
      }),
    cancel: (thread?: string) => send({ type: 'command.cancel', data: { thread } }),
    memoryClear: (thread?: string) =>
      send({ type: 'command.memory.clear', data: thread ? { thread } : {} }),
    configSet: (data) => send({ type: 'command.config.set', data }),
    sessionList: () => send({ type: 'command.session.list', data: {} }),
    hitlRespond: (requestId: string, decision: string, text?: string) =>
      send({ type: 'command.hitl.respond', data: { request_id: requestId, decision, text } }),
    feedback: (runId: string, rating: string, comment?: string) =>
      send({ type: 'command.feedback', data: { run_id: runId, rating, comment } }),
    snapshot: (thread?: string, label?: string) =>
      send({ type: 'command.snapshot.request', data: { thread, label } }),
    shutdown: () => send({ type: 'command.runtime.shutdown' }),
    kill,

    on: ((event: string, listener: (...args: unknown[]) => void) => {
      emitter.on(event, listener)
      return bridgeRef.current!
    }) as AGPBridge['on'],

    once: ((event: string, listener: (...args: unknown[]) => void) => {
      emitter.once(event, listener)
      return bridgeRef.current!
    }) as AGPBridge['once'],

    off: ((event: string, listener: (...args: unknown[]) => void) => {
      emitter.off(event, listener)
      return bridgeRef.current!
    }) as AGPBridge['off'],

    // AGPBridge narrows EventEmitter's emit/on overloads for AGP types; bind keeps runtime dispatch, cast satisfies the surface.
    emit: emitter.emit.bind(emitter) as AGPBridge['emit'],
  }

  bridgeRef.current = bridge
  return bridge
}
