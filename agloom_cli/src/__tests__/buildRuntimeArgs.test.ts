import { buildRuntimeArgs } from '../utils/buildRuntimeArgs.js'

describe('buildRuntimeArgs', () => {
  const base = {
    store: 'sqlite',
    thread: 't_test',
    sessionMaxTurns: 50,
    cliToolsWorkingDir: '/proj',
  }

  it('omits --no-harness by default', () => {
    const args = buildRuntimeArgs({ ...base, noHarness: false })
    expect(args).not.toContain('--no-harness')
  })

  it('forwards --no-harness when opted out', () => {
    const args = buildRuntimeArgs({ ...base, noHarness: true })
    expect(args).toEqual(expect.arrayContaining(['--no-harness']))
  })

  it('forwards --agent-store and --agent-store-path', () => {
    const args = buildRuntimeArgs({
      ...base,
      agentStore: 'sqlite',
      agentStorePath: '.agloom/custom.sqlite',
    })
    expect(args).toEqual(
      expect.arrayContaining(['--agent-store', 'sqlite', '--agent-store-path', '.agloom/custom.sqlite']),
    )
  })
})
