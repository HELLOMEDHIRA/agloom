/** Light mode: tweak `@inkjs/ui` defaults (e.g. ProgressBar). */

import { defaultTheme, extendTheme, type Theme } from '@inkjs/ui'
import type { AgloomTheme } from './themeContext.js'

export const buildInkUiTheme = (mode: AgloomTheme): Theme => {
  if (mode === 'dark') return defaultTheme
  return extendTheme(defaultTheme, {
    components: {
      ProgressBar: {
        styles: {
          completed: () => ({ color: 'blue' }),
        },
      },
    },
  })
}
