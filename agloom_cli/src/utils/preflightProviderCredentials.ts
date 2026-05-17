/**
 * Dry-run credential check using ``agloom-runtime providers resolve`` (same registry as Python).
 * Skips when model is ``auto`` / empty (nothing to resolve yet).
 */

import { spawnSync } from 'node:child_process'

export type PreflightResult = { ok: true } | { ok: false; message: string }

/** Parse ``--model`` / ``-m`` and ``--provider`` from argv-like arrays (e.g. ``buildRuntimeArgs`` output). */
export const modelAndProviderFromRuntimeArgs = (
  args: readonly string[],
): { model: string; provider: string | null } => {
  let model = ''
  let provider: string | null = null
  for (let i = 0; i < args.length; i++) {
    const a = args[i]
    if (a === '--model' || a === '-m') {
      const v = args[i + 1]
      if (v != null) {
        model = String(v).trim()
        i++
      }
    } else if (a === '--provider') {
      const v = args[i + 1]
      if (v != null) {
        const t = String(v).trim()
        provider = t.length > 0 ? t : null
        i++
      }
    }
  }
  return { model, provider }
}

const parseResolveOutput = (stdout: string): { keys: Array<{ key: string; set: boolean }>; hasEnvBlock: boolean } => {
  const lines = stdout.split(/\r?\n/)
  let inBlock = false
  const keys: Array<{ key: string; set: boolean }> = []
  for (const line of lines) {
    if (line.trim() === 'env_keys (registry):') {
      inBlock = true
      continue
    }
    if (!inBlock) continue
    const m = /^\s+([^:]+):\s+(set|unset)\s*$/.exec(line)
    if (m) {
      const key = (m[1] ?? '').trim()
      if (key) keys.push({ key, set: m[2] === 'set' })
      continue
    }
    if (keys.length > 0) break
  }
  return { keys, hasEnvBlock: stdout.includes('env_keys (registry):') }
}

/**
 * Returns ``ok: false`` when the resolved provider expects API keys and **none** of the
 * registry-listed env vars are set (per ``describe_resolve_dry_text`` output).
 */
export const preflightProviderCredentials = (
  modelSpec: string,
  provider?: string | null,
): PreflightResult => {
  const trimmed = modelSpec.trim()
  if (!trimmed || trimmed.toLowerCase() === 'auto') return { ok: true }

  const run = process.env['AGLOOM_RUNTIME'] ?? 'agloom-runtime'
  const args = ['providers', 'resolve', trimmed]
  const p = provider?.trim()
  if (p) {
    args.push('--provider', p)
  }
  const r = spawnSync(run, args, {
    encoding: 'utf8',
    shell: false,
    maxBuffer: 2_000_000,
    timeout: 30_000,
  })
  const out = `${r.stdout ?? ''}${r.stderr ?? ''}`
  if (r.error) {
    const code = (r.error as NodeJS.ErrnoException).code
    if (code === 'ETIMEDOUT' || code === 'ERR_SCRIPT_EXECUTION_TIMEOUT') {
      return {
        ok: false,
        message: `Model check timed out after 30s (${run} providers resolve).`,
      }
    }
  }
  if (r.error && (r.error as NodeJS.ErrnoException).code === 'ENOENT') {
    return {
      ok: false,
      message: `Cannot run ${run}: not found. Install the agloom Python package or set AGLOOM_RUNTIME.`,
    }
  }
  if (r.status !== 0) {
    return {
      ok: false,
      message: `Model check failed (${run} providers resolve exited ${r.status ?? 'unknown'}).\n${out.trim().slice(0, 800)}`,
    }
  }

  const { keys, hasEnvBlock } = parseResolveOutput(r.stdout ?? '')
  if (!hasEnvBlock || keys.length === 0) {
    return { ok: true }
  }
  if (keys.some((k) => k.set)) return { ok: true }

  const names = keys.map((k) => k.key).join(', ')
  return {
    ok: false,
    message: `No API credentials found for this model. Export one of: ${names}\n(or pass --api-key-env VAR with your key in VAR).`,
  }
}
