/**
 * Smoke tests for direct.ts — verifies exports and types.
 */
import type { DirectOpts } from '../../direct.js'

describe('DirectOpts interface', () => {
  it('has all required fields', () => {
    const opts: DirectOpts = {
      thread: 't1',
      quiet: true,
      json: false,
      noStream: false,
      noColor: false,
      noBanner: true,
      autoApprove: false,
      autoReject: false,
      hitlTty: false,
    }
    expect(opts.thread).toBe('t1')
    expect(opts.quiet).toBe(true)
  })
})
