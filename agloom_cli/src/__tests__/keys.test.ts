import { isCtrlY } from '../utils/keys.js'

describe('isCtrlY', () => {
  it('matches y / Y with ctrl', () => {
    expect(isCtrlY('y', { ctrl: true })).toBe(true)
    expect(isCtrlY('Y', { ctrl: true })).toBe(true)
    expect(isCtrlY('y', { ctrl: false })).toBe(false)
  })

  it('matches ASCII 25 (common Ctrl+Y wire form)', () => {
    expect(isCtrlY('\x19', { ctrl: true })).toBe(true)
    expect(isCtrlY('\u0019', { ctrl: true })).toBe(true)
  })
})
