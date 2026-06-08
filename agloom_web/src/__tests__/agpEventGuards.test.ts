import { describe, expect, it } from '@jest/globals'
import type { AGPEvent } from '../lib/agp/types.js'
import { isAgpEventType, isAgpKnownEvent } from '../lib/agp/agpEventGuards.js'

const base = {
  v: '1' as const,
  session: 's',
  seq: 1,
  ts: '2026-01-01T00:00:00Z',
  id: 'e1',
}

describe('agpEventGuards (web)', () => {
  it('narrows known catalogue events', () => {
    const evt: AGPEvent = {
      ...base,
      type: 'worker.halted',
      data: { worker_id: 'w1', reason: 'HALT_ALL' },
    }
    expect(isAgpKnownEvent(evt)).toBe(true)
    if (isAgpEventType(evt, 'worker.halted')) {
      expect(evt.data.worker_id).toBe('w1')
    } else {
      throw new Error('expected narrow')
    }
  })

  it('treats forward-compatible types as unknown', () => {
    const evt = {
      ...base,
      type: 'future.event',
      data: { foo: 1 },
    } as unknown as AGPEvent
    expect(isAgpKnownEvent(evt)).toBe(false)
    expect(isAgpEventType(evt, 'worker.halted')).toBe(false)
  })
})
