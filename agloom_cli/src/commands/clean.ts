/**
 * ``agloom clean`` — remove workspace artifacts created by agloom and agsuperbrain.
 * Deletes ``.agloom/``, ``.agsuperbrain/``, and related files from the project root.
 */

import { existsSync, readFileSync, writeFileSync, rmSync } from 'node:fs'
import { createInterface } from 'node:readline/promises'
import { join } from 'node:path'

import { resolveAgloomProjectRoot } from '../config.js'

export interface CleanCliOptions {
  dryRun?: boolean
  yes?: boolean
}

const CLEAN_TARGETS = [
  '.agloom',
  '.agsuperbrain',
  'agloom-progress.json',
]

const removeIfExists = (path: string): boolean => {
  if (existsSync(path)) {
    rmSync(path, { recursive: true, force: true })
    return true
  }
  return false
}

const planGitignoreClean = (root: string): { removed: boolean; lines: number; result?: string } => {
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
    return {
      removed: true,
      lines: original.split('\n').length - result.split('\n').length,
      result,
    }
  }
  return { removed: false, lines: 0 }
}

const cleanGitignore = (root: string): { removed: boolean; lines: number } => {
  const plan = planGitignoreClean(root)
  if (!plan.removed || plan.result == null) return { removed: false, lines: 0 }
  writeFileSync(join(root, '.gitignore'), plan.result, 'utf8')
  return { removed: true, lines: plan.lines }
}

const confirmClean = async (): Promise<boolean> => {
  if (!process.stdin.isTTY) return false
  const rl = createInterface({ input: process.stdin, output: process.stdout })
  try {
    const answer = await rl.question('  Remove agloom/agsuperbrain artifacts? [y/N] ')
    return /^y(es)?$/i.test(answer.trim())
  } finally {
    rl.close()
  }
}

export const runCleanCli = async (options: CleanCliOptions = {}): Promise<number> => {
  const root = resolveAgloomProjectRoot(process.cwd())
  const dryRun = options.dryRun === true

  process.stdout.write('\n')
  process.stdout.write('  ╔══════════════════════════════════════════════════════╗\n')
  process.stdout.write('  ║              agloom workspace clean                ║\n')
  process.stdout.write('  ╚══════════════════════════════════════════════════════╝\n')
  process.stdout.write('\n')

  const wouldRemove: string[] = []
  const notFound: string[] = []

  for (const target of CLEAN_TARGETS) {
    const fullPath = join(root, target)
    if (existsSync(fullPath)) {
      wouldRemove.push(target)
    } else {
      notFound.push(target)
    }
  }

  const gitPreview = planGitignoreClean(root)
  const gitWouldChange = gitPreview.removed

  if (dryRun) {
    process.stdout.write(`  Project root: ${root}\n\n`)
    process.stdout.write('  Dry run — would remove:\n')
    if (wouldRemove.length === 0 && !gitWouldChange) {
      process.stdout.write('    (nothing)\n')
    } else {
      for (const r of wouldRemove) {
        process.stdout.write(`    ✕ ${r}\n`)
      }
    }
    if (gitWouldChange) {
      process.stdout.write(
        `  Would clean .gitignore (remove ~${gitPreview.lines} agloom-related line(s))\n`,
      )
    }
    process.stdout.write('\n  Done (no files changed).\n\n')
    return 0
  }

  if (wouldRemove.length === 0 && !gitWouldChange) {
    process.stdout.write('  Nothing to clean — no agloom/agsuperbrain artifacts found.\n')
    process.stdout.write(`  (Scanned: ${root})\n`)
    process.stdout.write('  Done.\n\n')
    return 0
  }

  if (!options.yes) {
    const ok = await confirmClean()
    if (!ok) {
      process.stdout.write('  Cancelled.\n\n')
      return 0
    }
  }

  const removed: string[] = []
  for (const target of wouldRemove) {
    const fullPath = join(root, target)
    if (removeIfExists(fullPath)) {
      removed.push(target)
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
