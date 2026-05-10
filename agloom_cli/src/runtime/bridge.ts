/**
 * AGPBridge — spawns the Python `agloom-runtime serve --transport=stdio`
 * process and provides a typed EventEmitter interface over its NDJSON stream.
 *
 * Outbound (CLI → Python): JSON commands written to the child's stdin.
 * Inbound  (Python → CLI): NDJSON events read from the child's stdout.
 * Diagnostics: child's stderr forwarded via the 'diagnostic' event.
 *
 * Resolution order for the Python runtime binary:
 *   1. AGLOOM_RUNTIME env var (override)
 *   2. `agloom-runtime` (installed script via pip)
 */

import { spawn } from 'node:child_process'
import type { ChildProcess } from 'node:child_process'
import { EventEmitter } from 'node:events'
import type { AGPEvent, AGPCommand } from '../types/agp.js'
import { parseInboundAGPEventJSON } from '../types/agp.js'

export type BridgeStatus = 'starting' | 'ready' | 'error' | 'exited'

export interface BridgeExitInfo {
  code: number | null
  signal: string | null
}

/**
 * Declaration merging — provides fully-typed `on`/`once`/`off`/`emit`
 * overloads without conflicting with EventEmitter's own implementation
 * signatures (which is what caused `override` errors in TS 6).
 */
// eslint-disable-next-line @typescript-eslint/no-unsafe-declaration-merging
export interface AGPBridge {
  on(event: 'event', listener: (evt: AGPEvent) => void): this
  on(event: 'diagnostic', listener: (line: string) => void): this
  on(event: 'exit', listener: (info: BridgeExitInfo) => void): this
  on(event: 'error', listener: (err: Error) => void): this
  on(event: string, listener: (...args: unknown[]) => void): this

  once(event: 'event', listener: (evt: AGPEvent) => void): this
  once(event: 'diagnostic', listener: (line: string) => void): this
  once(event: 'exit', listener: (info: BridgeExitInfo) => void): this
  once(event: 'error', listener: (err: Error) => void): this
  once(event: string, listener: (...args: unknown[]) => void): this

  off(event: 'event', listener: (evt: AGPEvent) => void): this
  off(event: 'diagnostic', listener: (line: string) => void): this
  off(event: 'exit', listener: (info: BridgeExitInfo) => void): this
  off(event: 'error', listener: (err: Error) => void): this
  off(event: string, listener: (...args: unknown[]) => void): this

  emit(event: 'event', evt: AGPEvent): boolean
  emit(event: 'diagnostic', line: string): boolean
  emit(event: 'exit', info: BridgeExitInfo): boolean
  emit(event: 'error', err: Error): boolean
  emit(event: string, ...args: unknown[]): boolean
}

// eslint-disable-next-line @typescript-eslint/no-unsafe-declaration-merging
export class AGPBridge extends EventEmitter {
  public status: BridgeStatus = 'starting'
  public pid: number | undefined

  private proc: ChildProcess | null = null
  private buf = ''

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  /**
   * Spawn the Python runtime. `extraArgs` are appended after
   * `serve --transport=stdio` (e.g. `['--store', 'sqlite']`).
   */
  start(extraArgs: string[] = []): void {
    const cmd = process.env['AGLOOM_RUNTIME'] ?? 'agloom-runtime'
    const args = ['serve', '--transport=stdio', ...extraArgs]

    this.proc = spawn(cmd, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env },
      shell: false,
      // POSIX: create a new process group so we can kill by `-pid`; no-op on Windows.
      detached: process.platform !== 'win32',
    })

    this.pid = this.proc.pid

    // ── stdout: NDJSON event stream ──
    this.proc.stdout?.setEncoding('utf8')
    this.proc.stdout?.on('data', (chunk: string) => {
      this.buf += chunk
      const lines = this.buf.split('\n')
      this.buf = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue
        try {
          const evt = parseInboundAGPEventJSON(JSON.parse(trimmed))
          this.emit('event', evt)
          if (evt.type === 'session.opened') this.status = 'ready'
        } catch {
          this.emit('diagnostic', `[stdout] ${trimmed}`)
        }
      }
    })

    // ── stderr: diagnostic lines ──
    this.proc.stderr?.setEncoding('utf8')
    this.proc.stderr?.on('data', (chunk: string) => {
      for (const line of chunk.split('\n')) {
        const t = line.trim()
        if (t) this.emit('diagnostic', t)
      }
    })

    // ── process exit ──
    this.proc.on('exit', (code: number | null, signal: NodeJS.Signals | null) => {
      this.status = 'exited'
      this.emit('exit', { code, signal })
    })

    this.proc.on('error', (err: NodeJS.ErrnoException) => {
      const guidance =
        err.code === 'ENOENT'
          ? new Error(
              `Cannot find 'agloom-runtime'. ` +
                `Install agloom: pip install agloom\n` +
                `Or set AGLOOM_RUNTIME=/path/to/python to point to your interpreter.`
            )
          : err
      this.status = 'error'
      this.emit('error', guidance)
    })
  }

  // ── Command dispatch ───────────────────────────────────────────────────────

  send(cmd: AGPCommand): void {
    if (!this.proc?.stdin?.writable) return
    this.proc.stdin.write(JSON.stringify(cmd) + '\n')
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

  feedback(runId: string, rating: string, comment?: string): void {
    this.send({ type: 'command.feedback', data: { run_id: runId, rating, comment } })
  }

  snapshot(thread?: string, label?: string): void {
    this.send({ type: 'command.snapshot.request', data: { thread, label } })
  }

  shutdown(): void {
    this.send({ type: 'command.runtime.shutdown' })
  }

  kill(): void {
    if (!this.proc) return
    const pid = this.proc.pid
    if (pid == null) {
      this.proc.kill('SIGTERM')
      return
    }
    if (process.platform === 'win32') {
      // On Windows, SIGTERM only kills the top-level process; grandchildren (e.g. a uv subprocess)
      // are left orphaned. Use `taskkill /F /T` to kill the entire process tree.
      import('node:child_process').then(({ execSync }) => {
        try {
          execSync(`taskkill /F /T /PID ${pid}`, { stdio: 'ignore' })
        } catch {
          // Process may have already exited; swallow the error.
        }
      }).catch(() => {
        this.proc?.kill('SIGTERM')
      })
    } else {
      // POSIX: send SIGTERM to the process group so shell-spawned children are also signalled.
      try {
        process.kill(-pid, 'SIGTERM')
      } catch {
        this.proc.kill('SIGTERM')
      }
    }
  }
}
