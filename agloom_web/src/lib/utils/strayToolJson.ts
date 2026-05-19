/**
 * Detect assistant text that is JSON-shaped tool intent without native tool_calls
 * (mirrors ``agloom.patterns.react_tool_recovery``).
 */

const STRAY_TOOL_JSON_KEYS = new Set(['type', 'name', 'parameters', 'arguments', 'function', 'id'])

const toolNameFromStrayDict = (d: Record<string, unknown>): string | null => {
  const fn = d.function
  if (fn && typeof fn === 'object' && !Array.isArray(fn)) {
    const n = (fn as Record<string, unknown>).name
    if (typeof n === 'string' && n.trim()) return n.trim()
  }
  const n = d.name
  if (typeof n === 'string' && n.trim()) return n.trim()
  return null
}

const strayDictLooksLikeToolCall = (d: Record<string, unknown>): boolean => {
  if (d.type === 'function') return true
  if ('parameters' in d || 'arguments' in d) return true
  if (d.function && typeof d.function === 'object') return true
  const tname = toolNameFromStrayDict(d)
  if (!tname) return false
  return Object.keys(d).every((k) => STRAY_TOOL_JSON_KEYS.has(k))
}

export type StrayToolJsonOptions = {
  permissive?: boolean
}

export const isStrayToolJsonText = (
  text: string,
  allowedToolNames: ReadonlySet<string>,
  opts?: StrayToolJsonOptions,
): boolean => {
  const trimmed = text.trim()
  if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) return false
  let data: unknown
  try {
    data = JSON.parse(trimmed) as unknown
  } catch {
    return false
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return false
  const d = data as Record<string, unknown>
  if (!strayDictLooksLikeToolCall(d)) return false
  const tname = toolNameFromStrayDict(d)
  if (!tname) return false
  if (opts?.permissive) return true
  return allowedToolNames.size > 0 && allowedToolNames.has(tname)
}

const isWireLeakLine = (line: string): boolean => {
  const t = line.trim()
  if (!t) return false
  if (/^\s*content\s*=\s*['"]\[agloom:tool_result\]/i.test(t)) return true
  if (/^\s*content\s*=\s*['"]\{/.test(t) && t.includes('tool_result')) return true
  return false
}

const filterDisplayLines = (
  lines: string[],
  allowedToolNames: ReadonlySet<string>,
  opts?: StrayToolJsonOptions,
): string[] =>
  lines.filter((line) => {
    if (isWireLeakLine(line)) return false
    if (isStrayToolJsonText(line, allowedToolNames, opts)) return false
    return true
  })

export const stripStrayToolJsonFromStream = (
  streamed: string,
  allowedToolNames: ReadonlySet<string>,
  opts?: StrayToolJsonOptions,
): string => {
  if (!streamed) return streamed
  const permissive = opts?.permissive ?? allowedToolNames.size === 0
  const blocks = streamed.split(/\n{2,}/)
  const kept: string[] = []
  for (const block of blocks) {
    const lines = block.split('\n')
    const filtered = filterDisplayLines(lines, allowedToolNames, { permissive })
    if (filtered.length === 0) continue
    const merged = filtered.join('\n').trimEnd()
    if (merged && !isStrayToolJsonText(merged, allowedToolNames, { permissive })) {
      kept.push(merged)
    }
  }
  return kept.join('\n\n').trimEnd()
}
