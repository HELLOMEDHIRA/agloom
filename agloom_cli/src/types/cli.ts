/**
 * Shared CLI option types — single source of truth for both `index.tsx` and `config.ts`.
 */
export interface CoreCliOpts {
  thread?: string
  session?: string
  store: string
  storePath?: string
  diag: boolean
  noCliTools: boolean
  noRequireToolApproval: boolean
  noShellTool: boolean
  noNetworkTools: boolean
  unrestricted: boolean
  model?: string
  provider?: string
  apiKeyEnv?: string
  /** Forward ``--persist-api-key-in-session-marker`` (dangerous: key on disk). */
  persistApiKeyInSessionMarker?: boolean
  temperature?: number
  topP?: number
  topK?: number
  maxTokens?: number
  frequencyPenalty?: number
  presencePenalty?: number
  /** TUI compose from merged YAML only; default true when omitted. */
  multiline?: boolean
  mcp: string[]
  systemPrompt?: string
  systemPromptFile?: string
  memory?: string
  memoryPath?: string
  summarizerModel?: string
  noAutoSummarize: boolean
  sessionMaxTurns: number
  maxTurns?: number
  budgetTokens?: number
  budgetCostUsd?: number
  attach?: string[]
}
