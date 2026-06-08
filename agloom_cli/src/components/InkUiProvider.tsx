/** `@inkjs/ui` theme provider; merges light/dark from `useAgloomTheme`. */

import React, { useMemo } from 'react'
import { ThemeProvider as InkThemeProvider } from '@inkjs/ui'
import { useAgloomTheme } from '../themeContext.js'
import { buildInkUiTheme } from '../inkUiTheme.js'

export const InkUiProvider = ({ children }: { children: React.ReactNode }): React.ReactElement => {
  const mode = useAgloomTheme()
  const theme = useMemo(() => buildInkUiTheme(mode), [mode])
  return <InkThemeProvider theme={theme}>{children}</InkThemeProvider>
}
