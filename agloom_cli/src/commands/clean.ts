/**
 * ``agloom clean`` — remove workspace artifacts created by agloom and agsuperbrain.
 * Deletes ``.agloom/``, ``.agsuperbrain/``, and related files from the project root.
 */

import { existsSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'

const CLEAN_TARGETS = [
  '.agloom',
  '.agsuperbrain',
  'agloom-progress.json',
]

function findProjectRoot(start: string): string {
  let dir = start
  while (true) {
    if (existsSync(join(dir, '.git')) || existsSync(join(dir, 'agloom.yaml')) || existsSync(join(dir, '.agloom'))) {
      return dir
    }
    const parent = join(dir, '..')
    if (parent === dir) return start
    dir = parent
  }
}

function removeIfExists(path: string): boolean {
  if (existsSync(path)) {
    rmSync(path, { recursive: true, force: true })
    return true
  }
  return false
}

function cleanGitignore(root: string): { removed: boolean; lines: number } {
  const gitignorePath = join(root, '.gitignore')
  if (!existsSync(gitignorePath)) return { removed: false, lines: 0 }

  const original = readFileSync(gitignorePath, 'utf8')
  const agloomMarkers = [
    '# agloom',
    '# agloom-cli',
    '# agsuperbrain',
    '.agloom/',
    '.agsuperbrain/',
    'agloom-progress.json',
  ]

  const lines = original.split('\n').filter((line) => {
    const trimmed = line.trim()
    if (!trimmed) return true
    for (const marker of agloomMarkers) {
      if (trimmed === marker) return false
    }
    return true
  })

  // Remove consecutive blank lines
  const cleaned: string[] = []
  let prevBlank = false
  for (const line of lines) {
    const blank = line.trim() === ''
    if (blank && prevBlank) continue
    cleaned.push(line)
    prevBlank = blank
  }

  const result = cleaned.join('\n').trimEnd() + '\n'
  if (result !== original) {
    writeFileSync(gitignorePath, result, 'utf8')
    return { removed: true, lines: original.split('\n').length - result.split('\n').length }
  }
  return { removed: false, lines: 0 }
}

export async function runCleanCli(): Promise<number> {
  const root = findProjectRoot(process.cwd())

  process.stdout.write('\n')
  process.stdout.write('  ╔══════════════════════════════════════════════════════╗\n')
  process.stdout.write('  ║              agloom workspace clean                ║\n')
  process.stdout.write('  ╚══════════════════════════════════════════════════════╝\n')
  process.stdout.write('\n')

  const removed: string[] = []
  const notFound: string[] = []

  for (const target of CLEAN_TARGETS) {
    const fullPath = join(root, target)
    if (removeIfExists(fullPath)) {
      removed.push(target)
    } else {
      notFound.push(target)
    }
  }

  const git = cleanGitignore(root)

  // ── Results ──────────────────────────────────────────────────────────
  if (removed.length > 0) {
    process.stdout.write(`  Project root: ${root}\n\n`)
    process.stdout.write(`  Removed:\n`)
    for (const r of removed) {
      process.stdout.write(`    ✕ ${r}\n`)
    }
    process.stdout.write('\n')
  }

  if (git.removed) {
    process.stdout.write(`  Cleaned .gitignore (removed ${git.lines} agloom-related line(s))\n\n`)
  }

  if (removed.length === 0 && !git.removed) {
    process.stdout.write('  Nothing to clean — no agloom/agsuperbrain artifacts found.\n')
    process.stdout.write(`  (Scanned: ${root})\n`)
  }

  process.stdout.write('  Done.\n\n')
  return 0
}
