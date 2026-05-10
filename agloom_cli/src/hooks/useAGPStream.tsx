/**
 * useAGPStream — subscribes to an AGPBridge and pipes every event through
 * the zustand `dispatch` action.
 *
 * Also wires the 'diagnostic' and 'exit' events so the store reflects them.
 * Safe to call in strict-mode (idempotent registration via ref guard).
 */

import { useEffect, useRef } from 'react'
import type { AGPBridge } from '../runtime/bridge.js'
import { useSessionStore } from '../store/session.js'
import type { AGPEvent } from '../types/agp.js'

export const useAGPStream = (bridge: AGPBridge): void => {
  const dispatch = useSessionStore((s) => s.dispatch)
  const addDiagnostic = useSessionStore((s) => s.addDiagnostic)
  const markExited = useSessionStore((s) => s.markExited)

  // Ref-guard prevents double-subscription in React 18+ strict mode.
  const attachedRef = useRef(false)

  useEffect(() => {
    if (attachedRef.current) return
    attachedRef.current = true

    const onEvent = (evt: AGPEvent) => dispatch(evt)
    const onDiag = (line: string) => addDiagnostic(line)
    const onExit = () => markExited()
    const onError = (err: Error) =>
      addDiagnostic(`[bridge error] ${err.message}`)

    bridge.on('event', onEvent)
    bridge.on('diagnostic', onDiag)
    bridge.on('exit', onExit)
    bridge.on('error', onError)

    return () => {
      bridge.off('event', onEvent)
      bridge.off('diagnostic', onDiag)
      bridge.off('exit', onExit)
      bridge.off('error', onError)
      attachedRef.current = false
    }
  }, [bridge, dispatch, addDiagnostic, markExited])
}
