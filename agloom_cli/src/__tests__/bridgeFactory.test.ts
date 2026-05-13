/** Multi-bridge factory helpers. */

import { defaultAGPBridgeFactory, createBridges } from '../runtime/bridgeFactory'
import { createAGPBridge } from '../runtime/bridge'

describe('defaultAGPBridgeFactory', () => {
  it('creates independent bridges', () => {
    const f = defaultAGPBridgeFactory()
    const a = f.create()
    const b = f.create()
    expect(a).not.toBe(b)
    expect(typeof a.start).toBe('function')
  })

  it('disposeAll is safe on unstarted bridges', () => {
    const f = defaultAGPBridgeFactory()
    f.create()
    expect(() => f.disposeAll()).not.toThrow()
  })
})

describe('createBridges', () => {
  it('returns empty array for count 0', () => {
    expect(createBridges(0)).toHaveLength(0)
  })

  it('throws on negative count', () => {
    expect(() => createBridges(-1)).toThrow(RangeError)
  })
})

describe('createAGPBridge parity', () => {
  it('matches factory.create() shape', () => {
    const direct = createAGPBridge()
    const fromFactory = defaultAGPBridgeFactory().create()
    expect(Object.keys(direct).sort()).toEqual(Object.keys(fromFactory).sort())
  })
})
