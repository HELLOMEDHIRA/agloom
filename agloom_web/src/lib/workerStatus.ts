/** Tailwind text classes for worker lifecycle status (chat + runtime panels). */

export const workerLineClass = (status: string): string => {
  if (status === 'running') return 'text-yellow-400'
  if (status === 'done') return 'text-emerald-400'
  if (status === 'halted') return 'text-cyan-400'
  return 'text-red-400'
}

export const workerNameClass = (status: string): string => {
  if (status === 'halted') return 'text-cyan-400'
  if (status === 'failed') return 'text-red-400'
  return 'text-neutral-400'
}

export const workerIconClass = (status: string): string => {
  if (status === 'done') return 'text-emerald-400'
  if (status === 'running') return 'text-yellow-400'
  if (status === 'halted') return 'text-cyan-400'
  return 'text-red-400'
}
