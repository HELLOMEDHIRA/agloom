/** useAGPStream — subscribes to an AGPClient and pipes events into the store. */
import { useEffect, useRef } from 'react'
import type { AGPClient } from '../agp/client.js'
import { useSessionStore } from '../../store/session.js'

export const useAGPStream = (client: AGPClient): void => {
  const dispatch = useSessionStore((s) => s.dispatch)
  const setStatus = useSessionStore((s) => s.setConnectionStatus)
  const attached = useRef(false)

  useEffect(() => {
    if (attached.current) return
    attached.current = true

    const offEvent = client.onEvent(dispatch)
    const offStatus = client.onStatus((s) => setStatus(s as Parameters<typeof setStatus>[0]))

    return () => {
      offEvent()
      offStatus()
      attached.current = false
    }
  }, [client, dispatch, setStatus])
}
