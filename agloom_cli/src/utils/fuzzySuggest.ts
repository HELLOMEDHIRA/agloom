/** Lightweight history suggestions (no extra deps). */

function scoreContains(query: string, candidate: string): number {
  if (candidate.includes(query)) return 80 + Math.min(20, query.length)
  let n = 0
  for (const ch of query) {
    if (candidate.includes(ch)) n += 1
  }
  return n
}

export function suggestFromHistory(input: string, histLines: string[], limit = 3): string[] {
  const q = input.trim().toLowerCase()
  if (q.length < 2) return []
  const seen = new Set<string>()
  const scored: { line: string; s: number }[] = []
  for (const raw of histLines) {
    const line = raw.trim()
    if (line.length < 3 || line.startsWith('/')) continue
    const key = line.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    const s = scoreContains(q, key)
    if (s > 0) scored.push({ line, s })
  }
  scored.sort((a, b) => b.s - a.s)
  return scored.slice(0, limit).map((x) => x.line)
}
