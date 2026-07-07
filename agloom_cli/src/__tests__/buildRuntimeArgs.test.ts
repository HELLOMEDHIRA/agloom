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

  it('forwards --profile from YAML merge', () => {
    const args = buildRuntimeArgs({ ...base, profile: 'harness_long' })
    expect(args).toEqual(expect.arrayContaining(['--profile', 'harness_long']))
  })

  it('forwards execution and harness create_agent flags from YAML merge', () => {
    const args = buildRuntimeArgs({
      ...base,
      llmTimeout: 800,
      turnPlannerTimeout: 120,
      reactGraphTimeout: 900,
      reactRecursionLimit: 50,
      harnessProjectName: 'rca-platform',
      harnessGoal: 'Checkout latency RCA',
    })
    expect(args).toEqual(
      expect.arrayContaining([
        '--llm-timeout',
        '800',
        '--turn-planner-timeout',
        '120',
        '--react-graph-timeout',
        '900',
        '--react-recursion-limit',
        '50',
        '--harness-project-name',
        'rca-platform',
        '--harness-goal',
        'Checkout latency RCA',
      ]),
    )
  })
})
