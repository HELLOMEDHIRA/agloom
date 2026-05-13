import { TextDecoder } from 'node:util'
import { stdin } from 'node:process'

const _utf8Relaxed = new TextDecoder('utf-8', { fatal: false, ignoreBOM: true })

/**
 * When stdin is not a TTY, read the full stream (piped input). Returns empty string for TTY.
 * Trailing newline only is stripped from the concatenated buffer; inner/leading whitespace is preserved.
 * Uses a non-fatal UTF-8 decoder so binary or mixed streams do not throw (invalid bytes become U+FFFD).
 */
export async function readStdinIfPiped(): Promise<string> {
  if (stdin.isTTY) return ''
  return await new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    stdin.on('data', (c: Buffer) => {
      chunks.push(c)
    })
    stdin.on('end', () => {
      const raw = _utf8Relaxed.decode(Buffer.concat(chunks))
      // Do not ``String#trim()`` the whole buffer — that strips intentional leading/trailing spaces from pipes.
      resolve(raw.replace(/\r?\n$/, ''))
    })
    stdin.on('error', (e) => {
      reject(e)
    })
  })
}
