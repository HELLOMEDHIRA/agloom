import { suggestFromHistory } from '../utils/fuzzySuggest'

describe('suggestFromHistory', () => {
  it('returns empty for very short input', () => {
    expect(suggestFromHistory('a', ['hello world'], 3)).toEqual([])
  })

  it('matches substring of prior prompts', () => {
    const hist = ['refactor the auth module', 'hello', 'add tests for auth']
    const out = suggestFromHistory('auth', hist, 5)
    expect(out).toContain('refactor the auth module')
    expect(out).toContain('add tests for auth')
  })

  it('skips slash commands and dedupes', () => {
    const hist = ['/help', 'unique prompt alpha', 'unique prompt alpha', 'other']
    const out = suggestFromHistory('unique', hist, 5)
    expect(out.filter((l) => l.includes('unique'))).toEqual(['unique prompt alpha'])
  })
})
