import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { ensureAgloomCliWorkspace } from '../workspaceBootstrap.js'

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
    expect(existsSync(join(dir, '.agloom', 'mcp', 'agsuperbrain.yaml'))).toBe(true)
    expect(existsSync(join(dir, '.agloom', 'rules', 'README.txt'))).toBe(true)
    expect(existsSync(join(dir, '.agloom', 'AGLOOM_CONFIG_PATH.txt'))).toBe(true)
    expect(readFileSync(join(dir, '.agloom', 'AGLOOM_CONFIG_PATH.txt'), 'utf8')).toContain('.agloom')
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
})
