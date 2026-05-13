/** Wire validation for inbound AGP events (Zod). */

import { parseInboundAGPEventJSONWire } from '../types/agpWireParse'

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
})
