/** Factory for creating one or more {@link AGPBridge} instances (stdio child per bridge).
 * Use {@link defaultAGPBridgeFactory} from application code that needs a single bridge, or when you want {@link AGPBridgeFactory.disposeAll} to tear down every bridge the factory minted (tests, multi-session prototypes).
 */

import type { AGPBridge } from './bridge.js'
import { createAGPBridge } from './bridge.js'

export interface AGPBridgeFactory {
  /** Mint a new bridge (no process until ``start()``). */
  create(): AGPBridge
  /** Kill every bridge created by this factory that has not already exited. */
  disposeAll(): void
}

/** Default factory: each ``create()`` returns an independent stdio bridge. */
export function defaultAGPBridgeFactory(): AGPBridgeFactory {
  const minted: AGPBridge[] = []
  return {
    create() {
      const b = createAGPBridge()
      minted.push(b)
      return b
    },
    disposeAll() {
      for (const b of minted) {
        if (b.status !== 'exited') b.kill()
      }
      minted.length = 0
    },
  }
}

/** Create ``count`` bridges at once (same factory-backed disposal). */
export function createBridges(count: number, factory: AGPBridgeFactory = defaultAGPBridgeFactory()): AGPBridge[] {
  if (count < 0 || !Number.isFinite(count)) {
    throw new RangeError('createBridges: count must be a non-negative finite integer')
  }
  return Array.from({ length: Math.floor(count) }, () => factory.create())
}
