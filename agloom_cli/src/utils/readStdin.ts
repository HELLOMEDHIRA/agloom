import { stdin } from 'node:process'

/**
 * When stdin is not a TTY, read the full stream (piped input). Returns empty string for TTY.
 */
export async function readStdinIfPiped(): Promise<string> {
  if (stdin.isTTY) return ''
  return await new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    stdin.on('data', (c: Buffer) => {
      chunks.push(c)
    })
    stdin.on('end', () => {
      resolve(Buffer.concat(chunks).toString('utf8').trim())
    })
    stdin.on('error', (e) => {
      reject(e)
    })
  })
}
