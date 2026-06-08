import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { appendHistory, loadHistory } from '../utils/promptHistory.js'

describe('promptHistory', () => {
  let dir: string
  let path: string

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'agloom-ph-'))
    path = join(dir, 'history.json')
  })

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true })
  })

  it('appendHistory dedupes and caps length', () => {
    appendHistory(path, 'a')
    appendHistory(path, 'b')
    appendHistory(path, 'a')
    expect(loadHistory(path)).toEqual(['b', 'a'])
  })

  it('appendHistory replaces target via temp rename (atomic-ish)', () => {
    appendHistory(path, 'one')
    expect(existsSync(path)).toBe(true)
    const raw = readFileSync(path, 'utf8')
    expect(JSON.parse(raw.trim()) as unknown).toEqual(['one'])
    appendHistory(path, 'two')
    expect(loadHistory(path)).toEqual(['one', 'two'])
  })

  it('loadHistory tolerates corrupt JSON', () => {
    writeFileSync(path, 'not-json', 'utf8')
    expect(loadHistory(path)).toEqual([])
  })

  it('skips slash commands and blank lines', () => {
    appendHistory(path, '/help')
    appendHistory(path, '   ')
    appendHistory(path, 'ok')
    expect(loadHistory(path)).toEqual(['ok'])
  })
})
