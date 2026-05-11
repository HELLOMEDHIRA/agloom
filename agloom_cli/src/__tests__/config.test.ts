import { mkdirSync, mkdtempSync, rmSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { findWalkUpAgloomYaml, parseAgloomYamlFile } from '../config.js'

function writeYaml(content: string): string {
  const dir = mkdtempSync(join(tmpdir(), 'agloom-yaml-'))
  const p = join(dir, 'agloom.yaml')
  writeFileSync(p, content, 'utf8')
  return p
}

describe('findWalkUpAgloomYaml', () => {
  it('finds legacy .agloom/agloom.yaml when root agloom.yaml is absent', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-walk-'))
    const sub = join(dir, 'subdir')
    mkdirSync(sub, { recursive: true })
    const dot = join(dir, '.agloom')
    mkdirSync(dot, { recursive: true })
    const nested = join(dot, 'agloom.yaml')
    writeFileSync(nested, 'model: x\n', 'utf8')
    const found = findWalkUpAgloomYaml(sub)
    expect(found).toBe(nested)
    rmSync(dir, { recursive: true })
  })

  it('prefers project-root agloom.yaml over .agloom/agloom.yaml', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-walk2-'))
    const dot = join(dir, '.agloom')
    mkdirSync(dot, { recursive: true })
    writeFileSync(join(dot, 'agloom.yaml'), 'model: inner\n', 'utf8')
    const root = join(dir, 'agloom.yaml')
    writeFileSync(root, 'model: root\n', 'utf8')
    expect(findWalkUpAgloomYaml(dir)).toBe(root)
    rmSync(dir, { recursive: true })
  })
})

describe('parseAgloomYamlFile', () => {
  it('accepts object memory (drops to undefined) and map-style mcp', () => {
    const p = writeYaml(`
model: groq:meta-llama/llama-3.3-70b-versatile
memory:
  max_turns: 50
mcp:
  fs: ./mcp/filesystem.yaml
  gh:
    config: ./mcp/github.yaml
`)
    const y = parseAgloomYamlFile(p)
    expect(y.model).toBe('groq:meta-llama/llama-3.3-70b-versatile')
    expect(y.memory).toBeUndefined()
    expect(y.mcp).toEqual([
      'fs:./mcp/filesystem.yaml',
      { name: 'gh', config: './mcp/github.yaml' },
    ])
    unlinkSync(p)
  })

  it('still accepts string memory and array mcp', () => {
    const p = writeYaml(`
memory: sqlite
mcp:
  - fs: ./a.yaml
  - name: x
    config: ./b.yaml
`)
    const y = parseAgloomYamlFile(p)
    expect(y.memory).toBe('sqlite')
    expect(y.mcp).toEqual(['fs:./a.yaml', { name: 'x', config: './b.yaml' }])
    unlinkSync(p)
  })
})
