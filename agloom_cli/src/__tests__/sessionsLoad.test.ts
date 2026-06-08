import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'

import { loadSessions } from '../commands/sessionsLoad.js'

describe('loadSessions', () => {
  let dir: string
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'agloom-sess-'))
    mkdirSync(join(dir, '.agloom', 'sessions'), { recursive: true })
  })
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true })
  })

  it('reads model from effective_config when top-level model is absent', () => {
    const prev = process.cwd()
    try {
      process.chdir(dir)
      writeFileSync(
        join(dir, '.agloom', 'sessions', 'sess_test.json'),
        JSON.stringify({
          session_id: 'sess_test',
          started_at: '2026-05-01T12:00:00Z',
          initial_thread: 'thread_abc',
          transport: 'stdio',
          effective_config: { model: 'groq:meta-llama/llama-3.3-70b-versatile', provider_resolved: 'groq' },
        }),
        'utf8',
      )
      const rows = loadSessions()
      expect(rows).toHaveLength(1)
      expect(rows[0]!.id).toBe('sess_test')
      expect(rows[0]!.model).toContain('groq:')
      expect(rows[0]!.provider).toBe('groq')
    } finally {
      process.chdir(prev)
    }
  })
})
