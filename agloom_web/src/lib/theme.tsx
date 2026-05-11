/**
 * Theme: dark / light / system (persisted). Sets `html.dark` for Tailwind `dark:` variants.
 */
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

export type ThemeMode = 'dark' | 'light' | 'system'

const STORAGE_KEY = 'agloom.theme'

const readStoredMode = (): ThemeMode => {
  if (typeof window === 'undefined') return 'system'
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    /* ignore */
  }
  return 'system'
}

const prefersDark = (): boolean => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

const applyHtmlClass = (effective: 'dark' | 'light') => {
  if (typeof document === 'undefined') return
  document.documentElement.classList.toggle('dark', effective === 'dark')
}

interface ThemeContextValue {
  mode: ThemeMode
  effective: 'dark' | 'light'
  setMode: (m: ThemeMode) => void
  /** Cycle dark → light → system */
  cycle: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export const ThemeProvider = ({ children }: { children: React.ReactNode }): React.ReactElement => {
  const [mode, setModeState] = useState<ThemeMode>(readStoredMode)
  const [systemDark, setSystemDark] = useState(prefersDark)

  useEffect(() => {
    if (mode !== 'system' || typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const fn = () => setSystemDark(mq.matches)
    mq.addEventListener('change', fn)
    return () => mq.removeEventListener('change', fn)
  }, [mode])

  const effective: 'dark' | 'light' = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode

  useEffect(() => {
    applyHtmlClass(effective)
  }, [effective])

  const setMode = useCallback((m: ThemeMode) => {
    setModeState(m)
    try {
      localStorage.setItem(STORAGE_KEY, m)
    } catch {
      /* ignore */
    }
  }, [])

  const cycle = useCallback(() => {
    setModeState((prev) => {
      const order: ThemeMode[] = ['dark', 'light', 'system']
      const i = order.indexOf(prev)
      const next = order[(i + 1) % order.length] ?? 'system'
      try {
        localStorage.setItem(STORAGE_KEY, next)
      } catch {
        /* ignore */
      }
      return next
    })
  }, [])

  const value = useMemo(
    () => ({ mode, effective, setMode, cycle }),
    [mode, effective, setMode, cycle],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

/** Back-compat: `theme` === effective appearance; `toggle` cycles modes. */
export const useUiTheme = (): ThemeContextValue & {
  theme: 'dark' | 'light'
  setTheme: (t: 'dark' | 'light') => void
  toggle: () => void
} => {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useUiTheme must be used under ThemeProvider')
  const setTheme = (t: 'dark' | 'light') => ctx.setMode(t)
  return { ...ctx, theme: ctx.effective, setTheme, toggle: ctx.cycle }
}
