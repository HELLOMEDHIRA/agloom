import React, { createContext, useContext } from 'react'

export type AgloomTheme = 'dark' | 'light'

const ThemeCtx = createContext<AgloomTheme>('dark')

export function ThemeProvider({
  value,
  children,
}: {
  value: AgloomTheme
  children: React.ReactNode
}): React.ReactElement {
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>
}

export function useAgloomTheme(): AgloomTheme {
  return useContext(ThemeCtx)
}
