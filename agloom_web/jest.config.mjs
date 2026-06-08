/** @type {import('jest').Config} */
export default {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  testMatch: ['<rootDir>/src/__tests__/**/*.test.ts', '<rootDir>/src/__tests__/**/*.test.tsx'],
  moduleNameMapper: {
    // Strip .js extensions so ts-jest can resolve TypeScript sources
    '^(\\.{1,2}/.*)\\.js$': '$1',
    // Resolve @/ path alias
    '^@/(.*)$': '<rootDir>/src/$1',
  },
  transform: {
    '^.+\\.tsx?$': ['ts-jest', { tsconfig: 'tsconfig.test.json' }],
  },
}
