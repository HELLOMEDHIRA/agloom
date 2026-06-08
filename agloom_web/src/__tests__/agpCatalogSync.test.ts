/** Keep Zod wire schemas and web session reducer catalogue aligned (agloom_web only). */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { AGP_WIRE_DATA_EVENT_TYPES, AGP_WIRE_DATA_SCHEMAS } from '../lib/agp/agpWireParse.js'
import { KNOWN_AGP_EVENT_TYPES } from '../lib/agp/knownAgpEventTypes.js'

const contractPath = join(
  process.cwd(),
  '..',
  'agloom',
  'tests',
  'fixtures',
  'agp_wire_required_keys.json',
)
const wireContract = JSON.parse(readFileSync(contractPath, 'utf8')) as Record<string, string[]>

const symmetricDiff = (a: Set<string>, b: Set<string>): string[] =>
  [...a].filter((x) => !b.has(x)).concat([...b].filter((x) => !a.has(x))).sort()

function zodObjectKeys(schema: (typeof AGP_WIRE_DATA_SCHEMAS)[string]): Set<string> {
  if (!('shape' in schema) || typeof schema.shape !== 'object' || schema.shape === null) {
    throw new Error('expected ZodObject schema')
  }
  return new Set(Object.keys(schema.shape as Record<string, unknown>))
}

describe('AGP catalogue sync (web)', () => {
  it('KNOWN_AGP_EVENT_TYPES matches AGP_WIRE_DATA_EVENT_TYPES', () => {
    expect(symmetricDiff(KNOWN_AGP_EVENT_TYPES, AGP_WIRE_DATA_EVENT_TYPES)).toEqual([])
  })

  it('production Zod schemas expose keys from agp_wire_required_keys.json', () => {
    for (const [eventType, requiredKeys] of Object.entries(wireContract)) {
      const schema = AGP_WIRE_DATA_SCHEMAS[eventType]
      if (!schema) {
        throw new Error(`missing AGP_WIRE_DATA_SCHEMAS entry for ${eventType}`)
      }
      const shapeKeys = zodObjectKeys(schema)
      for (const key of requiredKeys) {
        expect(shapeKeys.has(key)).toBe(true)
      }
    }
  })

  it('contract event types are registered in AGP_WIRE_DATA_SCHEMAS', () => {
    for (const eventType of Object.keys(wireContract)) {
      expect(AGP_WIRE_DATA_SCHEMAS[eventType]).toBeDefined()
    }
  })
})
