/**
 * One-shot / piped execution mode — plain stdout (no Ink).
 */

import { createInterface } from 'node:readline/promises'
import stripAnsi from 'strip-ansi'
import type { AGPEvent, InvokeAttachment } from './types/agp.js'
import type { AGPBridge } from './runtime/bridge.js'
import { writeBannerToStderr } from './banner.js'

export interface DirectOpts {
  thread: string
  attachments?: InvokeAttachment[]
  quiet: boolean
  json: boolean
  noStream: boolean
  noColor: boolean
  noBanner: boolean
  autoApprove: boolean
  autoReject: boolean
  hitlTty: boolean
}

function waitForEvent(
  bridge: AGPBridge,
  pred: (e: AGPEvent) => boolean,
  ms = 120_000,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const onErr = (err: Error) => {
      clearTimeout(to)
      bridge.off('event', fn)
      bridge.off('error', onErr)
      reject(err)
    }
    const fn = (evt: AGPEvent) => {
      if (pred(evt)) {
        clearTimeout(to)
        bridge.off('error', onErr)
        bridge.off('event', fn)
        resolve()
      }
    }
    const to = setTimeout(() => {
      bridge.off('event', fn)
      bridge.off('error', onErr)
      reject(new Error('timed out waiting for AGP event'))
    }, ms)
    bridge.on('event', fn)
    bridge.on('error', onErr)
  })
}

export async function runDirect(options: {
  bridge: AGPBridge
  prompt: string
  opts: DirectOpts
  runtimeArgs: string[]
}): Promise<void> {
  const { bridge, prompt, opts, runtimeArgs } = options

  await writeBannerToStderr({
    quiet: opts.quiet,
    noBanner: opts.noBanner,
  })

  let inputTok = 0
  let outputTok = 0
  let costUsd = 0
  const t0 = Date.now()

  const writeOut = (s: string) => {
    const t = opts.noColor ? stripAnsi(s) : s
    process.stdout.write(t)
  }

  let hitlChain = Promise.resolve()
  const enqueueHitl = (fn: () => Promise<void>): void => {
    hitlChain = hitlChain.then(fn).catch((err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      process.stderr.write(`[agloom] HITL interactive prompt failed: ${msg}\n`)
    })
  }

  const onStream = (evt: AGPEvent) => {
    if (opts.json) {
      process.stdout.write(`${JSON.stringify(evt)}\n`)
      return
    }
    if (evt.type === 'metric.tokens') {
      inputTok += evt.data.input_tokens ?? 0
      outputTok += evt.data.output_tokens ?? 0
    }
    if (evt.type === 'metric.cost') {
      costUsd += evt.data.cost ?? 0
    }
    if (evt.type === 'token.delta' && !opts.noStream) {
      writeOut(evt.data.text)
    }
    if (evt.type === 'message.assistant' && opts.noStream) {
      writeOut(evt.data.content)
      if (!evt.data.content.endsWith('\n')) writeOut('\n')
    }

    if (evt.type === 'hitl.request') {
      const id = evt.data.request_id
      const tty = process.stdin.isTTY && process.stderr.isTTY
      if (opts.autoApprove) {
        bridge.hitlRespond(id, 'accept')
        return
      }
      if (opts.autoReject) {
        bridge.hitlRespond(id, 'reject')
        return
      }
      if (opts.hitlTty && tty) {
        enqueueHitl(async () => {
          const rl = createInterface({ input: process.stdin, output: process.stderr })
          try {
            const kind = evt.data.kind ?? 'gate'
            const tool = evt.data.tool ? ` (${evt.data.tool})` : ''
            const line = await rl.question(`[agloom] HITL ${kind}${tool} — approve? [y/N] `)
            const ok = line.trim().toLowerCase().startsWith('y')
            bridge.hitlRespond(id, ok ? 'accept' : 'reject')
          } finally {
            rl.close()
          }
        })
        return
      }
      bridge.hitlRespond(id, 'reject')
    }

    if (evt.type === 'session.closed') {
      const elapsed = ((Date.now() - t0) / 1000).toFixed(1)
      if (!opts.quiet && !opts.json) {
        process.stderr.write(
          `\n[agloom] done in ${elapsed}s · ${inputTok}↑ + ${outputTok}↓ tokens · $${costUsd.toFixed(4)}\n`,
        )
      }
      const reason = evt.data.reason
      process.exitCode =
        reason === 'completed' ? 0 : reason === 'user_aborted' ? 130 : reason === 'shutdown' ? 0 : 1
    }
  }

  bridge.on('event', onStream)

  const readyPromise = waitForEvent(
    bridge,
    (e) => e.type === 'session.opened' || e.type === 'runtime.ready',
  )

  bridge.start(runtimeArgs, { transport: 'stdio' })

  try {
    await readyPromise
  } catch (e) {
    bridge.off('event', onStream)
    throw e
  }

  bridge.invoke(prompt, opts.thread, opts.attachments)

  await new Promise<void>((resolve) => {
    const done = (evt: AGPEvent) => {
      if (evt.type === 'session.closed') {
        bridge.off('event', done)
        resolve()
      }
    }
    bridge.on('event', done)
    bridge.once('exit', () => {
      bridge.off('event', done)
      resolve()
    })
  })

  bridge.off('event', onStream)
  await hitlChain
  bridge.shutdown()
}
