/** Wire validation for inbound AGP events (Zod). */

import { parseInboundAGPEventJSONWire } from '../types/agpWireParse.js'

const baseEnv = {
  v: '1' as const,
  session: 's1',
  seq: 1,
  ts: '2026-01-01T00:00:00Z',
  id: 'evt_1',
}

describe('parseInboundAGPEventJSONWire', () => {
  it('accepts a valid session.opened', () => {
    const out = parseInboundAGPEventJSONWire({
      ...baseEnv,
      type: 'session.opened',
      data: { runtime_version: '0.2', protocol_version: '1', extra_future: true },
    })
    expect(out.type).toBe('session.opened')
    expect((out.data as Record<string, unknown>)['runtime_version']).toBe('0.2')
    expect((out.data as Record<string, unknown>)['extra_future']).toBe(true)
  })

  it('rejects session.opened missing protocol_version', () => {
    expect(() =>
      parseInboundAGPEventJSONWire({
        ...baseEnv,
        type: 'session.opened',
        data: { runtime_version: '0.2' },
      }),
    ).toThrow(/protocol_version/)
  })

  it('rejects invalid envelope', () => {
    expect(() =>
      parseInboundAGPEventJSONWire({
        v: '2',
        session: 's',
        seq: 1,
        ts: 't',
        id: 'i',
        type: 'session.opened',
        data: {},
      }),
    ).toThrow(/Invalid AGP envelope/)
  })

  it('accepts unknown type with object data', () => {
    const out = parseInboundAGPEventJSONWire({
      ...baseEnv,
      type: 'future.event',
      data: { foo: 1 },
    })
    expect(out.type).toBe('future.event')
    expect((out.data as Record<string, unknown>)['foo']).toBe(1)
  })

  it('rejects unknown type with non-object data (message names type)', () => {
    expect(() =>
      parseInboundAGPEventJSONWire({
        ...baseEnv,
        type: 'future.bad',
        data: 'not-an-object',
      }),
    ).toThrow(/future\.bad/)
  })

  it('accepts metric.budget.approaching with dimension enum', () => {
    const out = parseInboundAGPEventJSONWire({
      ...baseEnv,
      type: 'metric.budget.approaching',
      data: { dimension: 'tokens', used: 800, limit: 1000, ratio: 0.8 },
    })
    expect(out.type).toBe('metric.budget.approaching')
    expect((out.data as { dimension: string }).dimension).toBe('tokens')
  })

  it('rejects metric.budget.exhausted with invalid dimension', () => {
    expect(() =>
      parseInboundAGPEventJSONWire({
        ...baseEnv,
        type: 'metric.budget.exhausted',
        data: { dimension: 'requests', used: 1, limit: 1 },
      }),
    ).toThrow(/dimension/)
  })

  it('accepts worker.halted with optional preview', () => {
    const out = parseInboundAGPEventJSONWire({
      ...baseEnv,
      type: 'worker.halted',
      data: {
        worker_id: 'w1',
        reason: 'HALT_ALL',
        output_preview: 'stopped',
        duration_ms: 12,
      },
    })
    expect(out.type).toBe('worker.halted')
    expect((out.data as { worker_id: string }).worker_id).toBe('w1')
  })

  it('accepts thinking.step and plan.preview', () => {
    const think = parseInboundAGPEventJSONWire({
      ...baseEnv,
      type: 'thinking.step',
      data: { step: 'analyze', label: 'Analyzing', elapsed_ms: 40 },
    })
    expect((think.data as { label: string }).label).toBe('Analyzing')

    const plan = parseInboundAGPEventJSONWire({
      ...baseEnv,
      seq: 2,
      type: 'plan.preview',
      data: { pattern: 'react', steps: ['read', 'act'] },
    })
    expect((plan.data as { steps: string[] }).steps).toEqual(['read', 'act'])
  })

  it('rejects worker.halted missing worker_id', () => {
    expect(() =>
      parseInboundAGPEventJSONWire({
        ...baseEnv,
        type: 'worker.halted',
        data: { reason: 'HALT_ALL' },
      }),
    ).toThrow(/worker_id/)
  })
})
