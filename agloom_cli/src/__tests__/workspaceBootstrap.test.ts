import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { ensureAgloomCliWorkspace } from '../workspaceBootstrap.js'

describe('ensureAgloomCliWorkspace', () => {
  it('creates .agloom dirs and starter YAML when missing', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-ws-'))
    const { wroteYaml } = await ensureAgloomCliWorkspace(dir)
    expect(wroteYaml).toBe(true)
    expect(existsSync(join(dir, '.agloom', 'sessions'))).toBe(true)
    expect(existsSync(join(dir, '.agloom', 'rules'))).toBe(true)
    expect(existsSync(join(dir, 'agloom.yaml'))).toBe(true)
    expect(existsSync(join(dir, '.agloom', 'agloom.yaml'))).toBe(false)
    expect(readFileSync(join(dir, 'agloom.yaml'), 'utf8')).toContain('ai:')
    rmSync(dir, { recursive: true })
  })

  it('does not overwrite existing YAML files', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-ws2-'))
    mkdirSync(join(dir, '.agloom'), { recursive: true })
    const y = join(dir, 'agloom.yaml')
    const ny = join(dir, '.agloom', 'agloom.yaml')
    writeFileSync(y, 'model: preserve-root\n', 'utf8')
    writeFileSync(ny, 'model: preserve-nested\n', 'utf8')
    const { wroteYaml } = await ensureAgloomCliWorkspace(dir)
    expect(wroteYaml).toBe(false)
    expect(readFileSync(y, 'utf8')).toContain('preserve-root')
    expect(readFileSync(ny, 'utf8')).toContain('preserve-nested')
    rmSync(dir, { recursive: true })
  })

  it('does not create root agloom.yaml when legacy nested YAML exists alone', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agloom-ws3-'))
    mkdirSync(join(dir, '.agloom'), { recursive: true })
    const ny = join(dir, '.agloom', 'agloom.yaml')
    writeFileSync(ny, 'model: legacy-only\n', 'utf8')
    const { wroteYaml } = await ensureAgloomCliWorkspace(dir)
    expect(wroteYaml).toBe(false)
    expect(existsSync(join(dir, 'agloom.yaml'))).toBe(false)
    expect(readFileSync(ny, 'utf8')).toContain('legacy-only')
    rmSync(dir, { recursive: true })
  })
})
