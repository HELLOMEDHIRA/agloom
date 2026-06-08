import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { resolveAgloomProjectRoot } from '../config.js'

/** ``agloom clean`` uses the same root resolver as config — not ``.git`` walk-up. */
describe('agloom clean project root', () => {
  it('does not ascend to monorepo parent that only has .git and .agloom', () => {
    const repo = mkdtempSync(join(tmpdir(), 'agloom-clean-mono-'))
    mkdirSync(join(repo, '.git'), { recursive: true })
    mkdirSync(join(repo, '.agloom', 'sessions'), { recursive: true })

    const pkg = join(repo, 'packages', 'widget')
    const pkgSrc = join(pkg, 'src')
    mkdirSync(pkgSrc, { recursive: true })
    mkdirSync(join(pkg, '.agloom'), { recursive: true })
    writeFileSync(join(pkg, '.agloom', 'agloom.yaml'), 'model: local\n', 'utf8')

    expect(resolveAgloomProjectRoot(pkgSrc)).toBe(pkg)
    expect(resolveAgloomProjectRoot(pkgSrc)).not.toBe(repo)
    rmSync(repo, { recursive: true })
  })

  it('stays in cwd when no agloom yaml exists (does not match parent .agloom dir)', () => {
    const repo = mkdtempSync(join(tmpdir(), 'agloom-clean-noyaml-'))
    mkdirSync(join(repo, '.git'), { recursive: true })
    mkdirSync(join(repo, '.agloom'), { recursive: true })

    const child = join(repo, 'apps', 'demo')
    mkdirSync(child, { recursive: true })

    expect(resolveAgloomProjectRoot(child)).toBe(child)
    expect(existsSync(join(repo, '.agloom'))).toBe(true)
    rmSync(repo, { recursive: true })
  })
})
