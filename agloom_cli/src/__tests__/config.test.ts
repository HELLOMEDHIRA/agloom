import { mkdirSync, mkdtempSync, rmSync, unlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'

import { findWalkUpAgloomYaml, mcpSpecsFromYaml, parseAgloomYamlFile, resolveAgloomProjectRoot } from '../config.js'

const writeYaml=(content: string): string => {
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

  it('prefers .agloom/agloom.yaml over legacy root agloom.yaml when both exist', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-walk2-'))
    const dot = join(dir, '.agloom')
    mkdirSync(dot, { recursive: true })
    const nested = join(dot, 'agloom.yaml')
    writeFileSync(nested, 'model: inner\n', 'utf8')
    const root = join(dir, 'agloom.yaml')
    writeFileSync(root, 'model: root\n', 'utf8')
    expect(findWalkUpAgloomYaml(dir)).toBe(nested)
    rmSync(dir, { recursive: true })
  })
})

describe('resolveAgloomProjectRoot', () => {
  it('treats --config pointing at .agloom/agloom.yaml as project root parent', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-cfgnested-'))
    const nested = join(dir, '.agloom', 'agloom.yaml')
    mkdirSync(dirname(nested), { recursive: true })
    writeFileSync(nested, 'model: z\n', 'utf8')
    expect(resolveAgloomProjectRoot(join(dir, 'src'), nested)).toBe(dir)
    rmSync(dir, { recursive: true })
  })

  it('returns parent of project when cwd is a subdir and yaml is at root', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-root-'))
    writeFileSync(join(dir, 'agloom.yaml'), 'model: r\n', 'utf8')
    const sub = join(dir, 'pkg', 'src')
    mkdirSync(sub, { recursive: true })
    expect(resolveAgloomProjectRoot(sub)).toBe(dir)
    rmSync(dir, { recursive: true })
  })

  it('uses dirname(legacy nested yaml) parent as project root', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-nestedroot-'))
    const dot = join(dir, '.agloom')
    mkdirSync(dot, { recursive: true })
    writeFileSync(join(dot, 'agloom.yaml'), 'model: n\n', 'utf8')
    const sub = join(dir, 'deep')
    mkdirSync(sub, { recursive: true })
    expect(resolveAgloomProjectRoot(sub)).toBe(dir)
    rmSync(dir, { recursive: true })
  })
})

describe('mcpSpecsFromYaml', () => {
  it('resolves relative name:path against the YAML file directory', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-mcp-'))
    const yamlPath = join(dir, '.agloom', 'agloom.yaml')
    mkdirSync(dirname(yamlPath), { recursive: true })
    const want = resolve(dirname(yamlPath), 'mcp', 'agsuperbrain.yaml')
    expect(mcpSpecsFromYaml(['agsuperbrain:mcp/agsuperbrain.yaml'], yamlPath)).toEqual([`agsuperbrain:${want}`])
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

  it('flattens nested ai / memory / mcp.servers (Rich-era layout)', () => {
    const p = writeYaml(`
ai:
  model: auto
  system_prompt: "You are helpful."
memory:
  enabled: true
  max_turns: 42
mcp:
  servers:
    - fs:./mcp/fs.yaml
`)
    const y = parseAgloomYamlFile(p)
    expect(y.model).toBe('auto')
    expect(y.system_prompt).toBe('You are helpful.')
    expect(y.memory).toBe('sqlite')
    expect(y.session_max_turns).toBe(42)
    expect(y.mcp).toEqual(['fs:./mcp/fs.yaml'])
    unlinkSync(p)
  })

  it('flattens tools.cli_enabled and safety.require_approval', () => {
    const p = writeYaml(`
tools:
  cli_enabled: false
safety:
  require_approval: false
`)
    const y = parseAgloomYamlFile(p)
    expect(y.no_cli_tools).toBe(true)
    expect(y.require_tool_approval).toBe(false)
    unlinkSync(p)
  })

  it('flattens memory.auto_summarize and memory.summarizer_model', () => {
    const p = writeYaml(`
memory:
  max_turns: 80
  auto_summarize: false
  summarizer_model: groq:meta-llama/llama-3.3-70b-versatile
`)
    const y = parseAgloomYamlFile(p)
    expect(y.session_max_turns).toBe(80)
    expect(y.auto_summarize).toBe(false)
    expect(y.summarizer_model).toBe('groq:meta-llama/llama-3.3-70b-versatile')
    unlinkSync(p)
  })
})
