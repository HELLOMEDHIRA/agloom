import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

/** ASCII wordmark — spacing tuned for 80-col terminals. */
const WORDMARK = `
       ___    ____ __    ____  ____  __  ___
      /   |  / __// /   / __ \\/ __ \\/  |/  /
     / /| | / / _/ /   / / / / / / / /|_/ /
    / ___ |/ /__/ /___/ /_/ / /_/ / /  / /
   /_/  |_|\\___/_____/\\____/\\____/_/  /_/
`.trimEnd()

export interface BannerRuntimeHints {
  agentName?: string
  modelId?: string
  pattern?: string
  cliToolsCount?: number
}

export function formatBannerLine(opts: {
  version: string
  hints?: BannerRuntimeHints
  harnessOn?: boolean
}): string {
  const parts: string[] = []
  if (opts.hints?.modelId) parts.push(opts.hints.modelId)
  if (opts.hints?.pattern) parts.push(`pattern ${opts.hints.pattern}`)
  if (typeof opts.hints?.cliToolsCount === 'number') {
    parts.push(`${opts.hints.cliToolsCount} cli_tools`)
  }
  const meta = parts.length ? ` · ${parts.join(' · ')}` : ''
  const h = opts.harnessOn === undefined ? '' : opts.harnessOn ? ' · harness on' : ' · harness off'
  return `${WORDMARK}\n\n   agloom CLI v${opts.version}${meta}${h}\n   /help · Esc cancel · Ctrl+C exit\n`
}

export function bannerEnvDisabled(): boolean {
  const v = process.env['AGLOOM_BANNER']
  return v === '0' || v === 'false' || v === 'no'
}

/** Resolve package version from package.json next to dist (works from package root). */
export function readCliPackageVersion(): string {
  try {
    const here = fileURLToPath(new URL('.', import.meta.url))
    const pj = JSON.parse(readFileSync(`${here}/../package.json`, 'utf8')) as { version?: string }
    return pj.version ?? '0.0.0'
  } catch {
    return '0.0.0'
  }
}

export async function writeBannerToStderr(opts: {
  hints?: BannerRuntimeHints
  harnessOn?: boolean
  noBanner?: boolean
  quiet?: boolean
}): Promise<void> {
  if (opts.quiet || opts.noBanner || bannerEnvDisabled()) return
  const ver = readCliPackageVersion()
  process.stderr.write(`${formatBannerLine({ version: ver, hints: opts.hints, harnessOn: opts.harnessOn })}\n`)
}
