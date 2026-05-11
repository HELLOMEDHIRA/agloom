import { mkdtempSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { parseAgloomYamlFile } from '../config.js'

function writeYaml(content: string): string {
  const dir = mkdtempSync(join(tmpdir(), 'agloom-yaml-'))
  const p = join(dir, 'agloom.yaml')
  writeFileSync(p, content, 'utf8')
  return p
}

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
