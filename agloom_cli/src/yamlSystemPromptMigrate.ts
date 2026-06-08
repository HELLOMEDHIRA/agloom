/** Migrate legacy ``ai.system_prompt`` in ``.agloom/agloom.yaml``; persist user edits. */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'
import YAML from 'yaml'
import {
  CLI_WORKSPACE_SYSTEM_PROMPT,
  isCanonicalCliSystemPrompt,
  isLegacyCliSystemPrompt,
} from './cliWorkspacePrompt.js'

const extractSystemPrompt = (doc: Record<string, unknown>): string | null => {
  const ai = doc.ai
  if (ai && typeof ai === 'object' && !Array.isArray(ai)) {
    const sp = (ai as Record<string, unknown>).system_prompt
    if (typeof sp === 'string' && sp.trim()) return sp.trim()
  }
  const top = doc.system_prompt
  if (typeof top === 'string' && top.trim()) return top.trim()
  return null
}

const isUserTunedCliSystemPrompt = (text: string): boolean => {
  if (!text.trim()) return false
  if (isCanonicalCliSystemPrompt(text)) return false
  if (isLegacyCliSystemPrompt(text)) return false
  return true
}

const setYamlSystemPrompt = (rec: Record<string, unknown>, prompt: string): void => {
  const aiRaw = rec.ai
  const ai =
    aiRaw && typeof aiRaw === 'object' && !Array.isArray(aiRaw)
      ? { ...(aiRaw as Record<string, unknown>) }
      : {}
  ai.system_prompt = prompt.trim()
  rec.ai = ai
  if ('system_prompt' in rec) delete rec.system_prompt
}

/** Only rewrite outdated starter templates — never user-tuned or missing prompts. */
export const migrateLegacySystemPromptInYaml = (nestedYamlPath: string): boolean => {
  if (!existsSync(nestedYamlPath)) return false
  try {
    const raw = readFileSync(nestedYamlPath, 'utf8')
    const doc = YAML.parse(raw)
    if (doc == null || typeof doc !== 'object' || Array.isArray(doc)) return false
    const rec = doc as Record<string, unknown>
    const current = extractSystemPrompt(rec)
    if (!current || isCanonicalCliSystemPrompt(current)) return false
    if (isUserTunedCliSystemPrompt(current)) return false
    if (!isLegacyCliSystemPrompt(current)) return false
    setYamlSystemPrompt(rec, CLI_WORKSPACE_SYSTEM_PROMPT.trim())
    writeFileSync(nestedYamlPath, YAML.stringify(rec, { lineWidth: 120 }), 'utf8')
    return true
  } catch {
    return false
  }
}

/** Persist ``/system`` (or similar) into ``ai.system_prompt`` for the next CLI restart. */
export const persistUserSystemPromptToYaml = (nestedYamlPath: string, prompt: string): boolean => {
  const text = prompt.trim()
  if (!text) return false
  try {
    let rec: Record<string, unknown> = {}
    if (existsSync(nestedYamlPath)) {
      const doc = YAML.parse(readFileSync(nestedYamlPath, 'utf8'))
      if (doc != null && typeof doc === 'object' && !Array.isArray(doc)) {
        rec = doc as Record<string, unknown>
      }
    }
    setYamlSystemPrompt(rec, text)
    mkdirSync(dirname(nestedYamlPath), { recursive: true })
    writeFileSync(nestedYamlPath, YAML.stringify(rec, { lineWidth: 120 }), 'utf8')
    return true
  } catch {
    return false
  }
}
