import { isStrayToolJsonText, stripStrayToolJsonFromStream } from '../utils/strayToolJson.js'

describe('strayToolJson', () => {
  const tools = new Set(['read_file'])

  it('detects function-shaped stray JSON', () => {
    const t = JSON.stringify({
      type: 'function',
      name: 'read_file',
      parameters: { path: 'pyproject.toml', line_cap: 20 },
    })
    expect(isStrayToolJsonText(t, tools)).toBe(true)
  })

  it('ignores normal prose', () => {
    expect(isStrayToolJsonText('Hello world', tools)).toBe(false)
  })

  it('strips stray blocks from stream', () => {
    const stray = JSON.stringify({ name: 'read_file', parameters: { path: 'a.toml' } })
    const out = stripStrayToolJsonFromStream(`Intro line\n\n${stray}\n\n`, tools)
    expect(out).toBe('Intro line')
  })

  it('strips single-line stray JSON between prose lines', () => {
    const stray = JSON.stringify({
      type: 'function',
      name: 'read_file',
      parameters: { path: 'pyproject.toml', line_cap: 20 },
    })
    const out = stripStrayToolJsonFromStream(`Hello\n${stray}\nHere is the file.`, tools)
    expect(out).toBe('Hello\nHere is the file.')
  })

  it('strips permissive stray JSON before tool list arrives', () => {
    const stray = JSON.stringify({ name: 'read_file', parameters: { path: 'a.toml' } })
    const out = stripStrayToolJsonFromStream(stray, new Set(), { permissive: true })
    expect(out).toBe('')
  })

  it('strips wire-leak repr lines', () => {
    const out = stripStrayToolJsonFromStream(
      "content='[agloom:tool_result] complete=true\\n1|[project]",
      tools,
    )
    expect(out).toBe('')
  })
})
