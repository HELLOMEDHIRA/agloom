import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooksPlugin from 'eslint-plugin-react-hooks'

export default tseslint.config(
  // Base JS recommended
  js.configs.recommended,

  // TypeScript recommended
  ...tseslint.configs.recommended,

  // React Hooks — prevents hooks-of-hooks and exhaustive-deps violations
  reactHooksPlugin.configs.flat['recommended-latest'],

  // Project-wide overrides
  {
    files: ['src/**/*.{ts,tsx}'],
    rules: {
      'no-var': 'error',
      'prefer-const': 'error',
      'object-shorthand': ['error', 'always'],
      'prefer-template': 'error',
      'prefer-rest-params': 'error',
      'prefer-spread': 'error',
      'prefer-exponentiation-operator': 'error',
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/explicit-module-boundary-types': 'off',
      '@typescript-eslint/no-require-imports': 'error',
    },
  },

  // Ignore build outputs and config files
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**'],
  },
)
