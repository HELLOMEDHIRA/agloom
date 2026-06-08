import { modelAndProviderFromRuntimeArgs } from '../utils/preflightProviderCredentials.js'

describe('modelAndProviderFromRuntimeArgs', () => {
  it('parses --model and --provider', () => {
    expect(
      modelAndProviderFromRuntimeArgs(['--store', 'sqlite', '--model', 'nvidia:foo', '--provider', 'nvidia']),
    ).toEqual({ model: 'nvidia:foo', provider: 'nvidia' })
  })

  it('parses -m shorthand', () => {
    expect(modelAndProviderFromRuntimeArgs(['-m', 'openai:gpt-4o'])).toEqual({
      model: 'openai:gpt-4o',
      provider: null,
    })
  })

  it('returns empty model when flag missing', () => {
    expect(modelAndProviderFromRuntimeArgs(['--store', 'none'])).toEqual({ model: '', provider: null })
  })

  it('uses last occurrence when repeated', () => {
    expect(
      modelAndProviderFromRuntimeArgs(['--model', 'a', '--model', 'b', '--provider', 'x', '--provider', 'y']),
    ).toEqual({ model: 'b', provider: 'y' })
  })
})
