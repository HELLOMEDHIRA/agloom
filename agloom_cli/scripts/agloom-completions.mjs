#!/usr/bin/env node
/**
 * Print shell completion scripts to stdout for redirection, e.g.:
 *   agloom-completions bash >> ~/.bashrc
 *   agloom-completions zsh  > ~/.zfunc/_agloom
 *   agloom-completions fish > ~/.config/fish/completions/agloom.fish
 */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'completions')
const shell = process.argv[2]?.toLowerCase()
const map = { bash: 'agloom.bash', zsh: '_agloom', fish: 'agloom.fish' }

if (!shell || map[shell] === undefined) {
  process.stderr.write(
    `Usage: agloom-completions <bash|zsh|fish>\nWrites the completion script for that shell to stdout.\n`,
  )
  process.exit(1)
}

process.stdout.write(readFileSync(join(root, map[shell]), 'utf8'))
