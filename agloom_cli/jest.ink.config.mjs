/**
 * Terminal UI tests (yoga-layout) need native ESM (top-level await, import.meta). Run with:
 *   node --experimental-vm-modules ./node_modules/jest/bin/jest.js --config jest.ink.config.mjs
 */
/** @type {import('jest').Config} */
export default {
  preset: 'ts-jest',
  testEnvironment: 'node',
  testMatch: ['<rootDir>/src/__tests__/components/**/*.test.ts', '<rootDir>/src/__tests__/components/**/*.test.tsx'],
  extensionsToTreatAsEsm: ['.ts', '.tsx'],
  moduleNameMapper: {
    '^(\\.{1,2}/.*)\\.js$': '$1',
  },
  transform: {
    '^.+\\.tsx?$': [
      'ts-jest',
      {
        useESM: true,
        tsconfig: 'tsconfig.test-esm.json',
      },
    ],
  },
}
