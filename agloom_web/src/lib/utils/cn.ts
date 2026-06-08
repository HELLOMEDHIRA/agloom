import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export const cn = (...inputs: ClassValue[]): string => {
  return twMerge(clsx(inputs))
}

export const truncate = (s: string, max: number): string => {
  if (!s) return ''
  return s.length <= max ? s : `${s.slice(0, max - 1)}…`
}

export const fmtDuration = (ms: number | undefined): string => {
  if (ms === undefined) return ''
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60_000)}m${Math.floor((ms % 60_000) / 1000)}s`
}

export const fmtTokens = (n: number): string => {
  return n < 1000 ? `${n}` : `${(n / 1000).toFixed(1)}k`
}

/** Compact JSON args for tool rows (B3). */
export const fmtArgs = (args: Record<string, unknown>, maxLen = 60): string => {
  try {
    const s = JSON.stringify(args)
    return truncate(s.replace(/\s+/g, ' ').trim(), maxLen)
  } catch {
    return '{…}'
  }
}
