import { fmtTokens } from './cn.js'

const AGLOOM_TOOL_RESULT_RE = /^\[agloom:tool_result\]\s*complete=(?:true|false)\s*\n?/i

export const stripAgloomToolResultEnvelope = (s: string): string => {
  let t = s
  while (AGLOOM_TOOL_RESULT_RE.test(t)) {
    t = t.replace(AGLOOM_TOOL_RESULT_RE, '')
  }
  return t.trim()
}

export const finalizeAssistantMessage = (wireContent: string, streamed: string): string => {
  const wire = stripAgloomToolResultEnvelope(wireContent)
  const stream = stripAgloomToolResultEnvelope(streamed)
  if (wire && stream) {
    if (wire.includes(stream)) return wire
    if (stream.includes(wire)) return stream
    return wire.length >= stream.length ? wire : stream
  }
  return wire || stream
}

export const formatTurnTokenRollup = (inputTokens: number, outputTokens: number): string | undefined => {
  if (inputTokens <= 0 && outputTokens <= 0) return undefined
  if (inputTokens > 0 && outputTokens > 0) {
    return `↑${fmtTokens(inputTokens)} ↓${fmtTokens(outputTokens)}`
  }
  if (inputTokens > 0) return `↑${fmtTokens(inputTokens)}`
  return `↓${fmtTokens(outputTokens)}`
}
