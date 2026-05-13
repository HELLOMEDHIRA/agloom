/** ``agloom upgrade`` — compare local CLI + Python package versions to npm/PyPI latest. */

import { readCliPackageVersion } from '../banner.js'

async function fetchJson(url: string): Promise<unknown> {
  const res = await fetch(url, { redirect: 'follow' })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return (await res.json()) as unknown
}

export async function runUpgradeCli(): Promise<number> {
  const localCli = readCliPackageVersion()
  let latestCli = '?'
  try {
    const j = (await fetchJson('https://registry.npmjs.org/agloom-cli/latest')) as { version?: string }
    latestCli = j.version ?? '?'
  } catch {
    latestCli = '(npm unreachable)'
  }

  let localPy = '?'
  try {
    const { spawnSync } = await import('node:child_process')
    const run = process.env['AGLOOM_RUNTIME'] ?? 'agloom-runtime'
    const r = spawnSync(run, ['version'], { encoding: 'utf8', shell: false, maxBuffer: 64 })
    localPy = (r.stdout ?? '').trim().split(/\r?\n/)[0] || '?'
  } catch {
    localPy = '(agloom-runtime not on PATH)'
  }

  let latestPy = '?'
  try {
    const j = (await fetchJson('https://pypi.org/pypi/agloom/json')) as { info?: { version?: string } }
    latestPy = j.info?.version ?? '?'
  } catch {
    latestPy = '(pypi unreachable)'
  }

  process.stdout.write('agloom upgrade — version check\n\n')
  process.stdout.write(`npm package agloom-cli\n  installed: ${localCli}\n  latest:    ${latestCli}\n`)
  process.stdout.write(`\nPyPI package agloom\n  installed: ${localPy}\n  latest:    ${latestPy}\n`)
  process.stdout.write('\nSuggested:\n')
  process.stdout.write('  npm i -g agloom-cli@latest\n')
  process.stdout.write('  pip install -U agloom\n')
  return 0
}
