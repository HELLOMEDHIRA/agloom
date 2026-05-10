import { TextDecoder, TextEncoder } from 'node:util'
import '@testing-library/jest-dom'

/** react-router-dom expects TextEncoder in the JS global scope (browser baseline). */
globalThis.TextEncoder = TextEncoder
globalThis.TextDecoder = TextDecoder as typeof globalThis.TextDecoder
