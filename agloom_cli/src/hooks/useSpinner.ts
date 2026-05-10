/**
 * useSpinner — returns a single rotating spinner character.
 * Used in place of ink-spinner when we need a simple inline indicator.
 */

import { useEffect, useState } from 'react'

const FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

export function useSpinner(intervalMs = 80): string {
  const [frame, setFrame] = useState(0)

  useEffect(() => {
    const id = setInterval(() => setFrame((f) => (f + 1) % FRAMES.length), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])

  return FRAMES[frame] ?? '⠋'
}
