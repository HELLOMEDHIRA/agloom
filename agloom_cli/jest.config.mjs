/** @type {import('jest').Config} */
export default {
  preset: 'ts-jest',
  testEnvironment: 'node',
  testMatch: ['<rootDir>/src/__tests__/**/*.test.ts', '<rootDir>/src/__tests__/**/*.test.tsx'],
  testPathIgnorePatterns: ['[/\\\\]src[/\\\\]__tests__[/\\\\]components[/\\\\]'],
  moduleNameMapper: {
    // ts-jest: strip .js extensions so it finds .ts sources
    '^(\\.{1,2}/.*)\\.js$': '$1',
  },
  transform: {
    '^.+\\.tsx?$': ['ts-jest', { tsconfig: 'tsconfig.test.json' }],
  },
}
