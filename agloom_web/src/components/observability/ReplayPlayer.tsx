/**
 * ReplayPlayer — SSE-based session replay with speed control.
 * Feeds replayed envelopes directly into the Zustand store — identical rendering to live.
 */
import React, { useEffect, useRef, useState } from 'react'
import { obsApi } from '../../lib/agp/obsApi.js'
import { useSessionStore } from '../../store/session.js'
import type { AGPEvent } from '../../lib/agp/types.js'
import { Play, Pause, RotateCcw, Zap } from 'lucide-react'
import { cn } from '../../lib/utils/cn.js'
import { CompletedTurnCard } from '../chat/CompletedTurnCard.js'
import { StreamingTurn } from '../chat/StreamingTurn.js'

interface Props { sessionId: string }

const SPEEDS = [0.5, 1, 2, 5, 0] as const
const SPEED_LABELS: Record<number, string> = { 0.5: '0.5×', 1: '1×', 2: '2×', 5: '5×', 0: 'instant' }

export function ReplayPlayer({ sessionId }: Props): React.ReactElement {
  const [speed, setSpeed] = useState<number>(1)
  const [playing, setPlaying] = useState(false)
  const [done, setDone] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  const dispatch   = useSessionStore((s) => s.dispatch)
  const reset      = useSessionStore((s) => s.reset)
  const completed  = useSessionStore((s) => s.completedTurns)
  const active     = useSessionStore((s) => s.activeTurn)

  const startReplay = () => {
    reset()
    setDone(false)
    setPlaying(true)

    const url = obsApi.replayUrl(sessionId, speed)
    const es = new EventSource(url)
    esRef.current = es

    es.onmessage = (e) => {
      try {
        const envelope = JSON.parse(e.data as string) as AGPEvent | { type: 'replay.done' }
        if (envelope.type === 'replay.done') {
          setPlaying(false)
          setDone(true)
          es.close()
          return
        }
        dispatch(envelope as AGPEvent)
      } catch { /* malformed */ }
    }

    es.onerror = () => {
      setPlaying(false)
      es.close()
    }
  }

  const stopReplay = () => {
    esRef.current?.close()
    esRef.current = null
    setPlaying(false)
  }

  useEffect(() => () => esRef.current?.close(), [])

  return (
    <div className="flex flex-col h-full">
      {/* Controls */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-neutral-800 bg-neutral-950 shrink-0">
        <button
          onClick={playing ? stopReplay : startReplay}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
            playing ? 'bg-red-800 hover:bg-red-700 text-white' : 'bg-indigo-700 hover:bg-indigo-600 text-white'
          )}
        >
          {playing ? <Pause size={11} /> : <Play size={11} />}
          {playing ? 'Stop' : 'Replay'}
        </button>

        {!playing && (
          <button onClick={() => { reset(); setDone(false) }} className="flex items-center gap-1 px-2 py-1.5 text-xs text-neutral-500 hover:text-neutral-300 transition-colors">
            <RotateCcw size={11} />
          </button>
        )}

        {/* Speed selector */}
        <div className="flex items-center gap-1 ml-auto">
          <Zap size={10} className="text-neutral-600" />
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              disabled={playing}
              className={cn(
                'px-2 py-1 rounded text-xs transition-colors',
                speed === s ? 'bg-neutral-700 text-white' : 'text-neutral-500 hover:text-neutral-300'
              )}
            >
              {SPEED_LABELS[s]}
            </button>
          ))}
        </div>
      </div>

      {/* Replay content — same rendering as live chat */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {done && completed.length === 0 && (
          <p className="text-sm text-neutral-600 text-center py-8">No events replayed. Session may be empty.</p>
        )}
        {!playing && !done && completed.length === 0 && (
          <p className="text-sm text-neutral-500 text-center py-8">
            Press <strong>Replay</strong> to re-play this session at the selected speed.
          </p>
        )}
        {completed.map((turn) => <CompletedTurnCard key={turn.id} turn={turn} />)}
        {active && <StreamingTurn turn={active} />}
        {done && <p className="text-xs text-emerald-500 text-center py-2">✓ Replay complete</p>}
      </div>
    </div>
  )
}
