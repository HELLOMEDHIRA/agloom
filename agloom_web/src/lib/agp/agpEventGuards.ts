/** Narrow ``AGPEvent`` without ``UnknownAgpEvent`` widening known ``type`` literals. */

import type { AGPEvent, AGPKnownEvent } from './types.js'
import { KNOWN_AGP_EVENT_TYPES } from './knownAgpEventTypes.js'

export type AGPKnownEventType = AGPKnownEvent['type']

export const isAgpKnownEvent = (evt: AGPEvent): evt is AGPKnownEvent =>
  KNOWN_AGP_EVENT_TYPES.has(evt.type)

/** True when ``evt`` is a catalogue event with the given ``type`` (narrows ``data``). */
export const isAgpEventType = <T extends AGPKnownEventType>(
  evt: AGPEvent,
  type: T,
): evt is Extract<AGPKnownEvent, { type: T }> => evt.type === type
