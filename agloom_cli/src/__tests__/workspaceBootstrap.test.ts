import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { ensureAgloomCliWorkspace, ensureAgsuperbrainMcpInNestedYaml, stripMemorySkillsEnabledFromYamlText } from '../workspaceBootstrap.js'

describe('ensureAgloomCliWorkspace', () => {
  it('creates .agloom dirs and starter .agloom/agloom.yaml when missing', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-ws-'))
    const nestedCfg = join(dir, '.agloom', 'agloom.yaml')
    const { wroteYaml } = await ensureAgloomCliWorkspace(dir, { configPath: nestedCfg })
    expect(wroteYaml).toBe(true)
    expect(existsSync(join(dir, '.agloom', 'sessions'))).toBe(true)
    expect(existsSync(join(dir, '.agloom', 'rules'))).toBe(true)
    expect(existsSync(nestedCfg)).toBe(true)
    expect(existsSync(join(dir, 'agloom.yaml'))).toBe(false)
    expect(readFileSync(nestedCfg, 'utf8')).toContain('ai:')
    expect(readFileSync(nestedCfg, 'utf8')).toContain('agsuperbrain:mcp/agsuperbrain.yaml')
    expect(existsSync(join(dir, '.agloom', 'mcp', 'agsuperbrain.yaml'))).toBe(true)
    expect(existsSync(join(dir, '.agloom', 'rules', 'README.txt'))).toBe(true)
    rmSync(dir, { recursive: true })
  })

  it('does not overwrite existing YAML files', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-ws2-'))
    mkdirSync(join(dir, '.agloom'), { recursive: true })
    const y = join(dir, 'agloom.yaml')
    const ny = join(dir, '.agloom', 'agloom.yaml')
    writeFileSync(y, 'model: preserve-root\n', 'utf8')
    writeFileSync(ny, 'model: preserve-nested\n', 'utf8')
    const { wroteYaml } = await ensureAgloomCliWorkspace(dir, { configPath: y })
    expect(wroteYaml).toBe(false)
    expect(readFileSync(y, 'utf8')).toContain('preserve-root')
    expect(readFileSync(ny, 'utf8')).toContain('preserve-nested')
    rmSync(dir, { recursive: true })
  })

  it('copies root agloom.yaml into .agloom when nested is missing', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-ws-migrate-'))
    mkdirSync(join(dir, '.agsuperbrain'), { recursive: true })
    const rootY = join(dir, 'agloom.yaml')
    writeFileSync(rootY, 'model: from-root-only\n', 'utf8')
    const nestedCfg = join(dir, '.agloom', 'agloom.yaml')
    const { wroteYaml } = await ensureAgloomCliWorkspace(dir, { configPath: rootY })
    expect(wroteYaml).toBe(true)
    expect(readFileSync(nestedCfg, 'utf8')).toContain('from-root-only')
    expect(readFileSync(nestedCfg, 'utf8')).toContain('agsuperbrain:mcp/agsuperbrain.yaml')
    expect(readFileSync(rootY, 'utf8')).toContain('from-root-only')
    rmSync(dir, { recursive: true })
  })

  it('does not create root agloom.yaml when nested YAML exists alone', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-ws3-'))
    mkdirSync(join(dir, '.agloom'), { recursive: true })
    const ny = join(dir, '.agloom', 'agloom.yaml')
    writeFileSync(ny, 'model: legacy-only\n', 'utf8')
    const { wroteYaml } = await ensureAgloomCliWorkspace(dir, { configPath: ny })
    expect(wroteYaml).toBe(false)
    expect(existsSync(join(dir, 'agloom.yaml'))).toBe(false)
    expect(readFileSync(ny, 'utf8')).toContain('legacy-only')
    rmSync(dir, { recursive: true })
  })

  it('strips deprecated memory.enabled / skills.enabled from nested yaml on ensure', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-ws-strip-'))
    mkdirSync(join(dir, '.agloom'), { recursive: true })
    mkdirSync(join(dir, '.agsuperbrain'), { recursive: true })
    const ny = join(dir, '.agloom', 'agloom.yaml')
    writeFileSync(
      ny,
      'ai:\n  model: auto\nmemory:\n  enabled: true\n  max_turns: 50\nskills:\n  enabled: true\n  max_skills: 30\n',
      'utf8',
    )
    const { wroteYaml } = await ensureAgloomCliWorkspace(dir, { configPath: ny })
    expect(wroteYaml).toBe(false)
    const body = readFileSync(ny, 'utf8')
    expect(body).toContain('max_turns: 50')
    expect(body).not.toContain('memory:\n  enabled:')
    expect(body).not.toContain('skills:\n  enabled:')
    rmSync(dir, { recursive: true })
  })
})

describe('stripMemorySkillsEnabledFromYamlText', () => {
  it('removes only memory/skills enabled keys', () => {
    const raw =
      '# c\nmemory:\n  enabled: true\n  max_turns: 50\nskills:\n  enabled: false\n  max_skills: 3\ntools:\n  cli_enabled: true\n'
    const { text, changed } = stripMemorySkillsEnabledFromYamlText(raw)
    expect(changed).toBe(true)
    expect(text).not.toContain('memory:\n  enabled:')
    expect(text).not.toContain('skills:\n  enabled:')
    expect(text).toContain('cli_enabled: true')
    expect(text).toContain('max_turns: 50')
  })
})

describe('ensureAgsuperbrainMcpInNestedYaml', () => {
  it('injects agsuperbrain shorthand when mcp.servers is missing', () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-mcp-patch-'))
    const p = join(dir, 'agloom.yaml')
    writeFileSync(p, 'ai:\n  name: t\n  model: auto\n', 'utf8')
    ensureAgsuperbrainMcpInNestedYaml(p)
    expect(readFileSync(p, 'utf8')).toContain('agsuperbrain:mcp/agsuperbrain.yaml')
    rmSync(dir, { recursive: true })
  })
})
