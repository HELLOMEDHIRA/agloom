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
  temperature?: number
  topP?: number
  topK?: number
  maxTokens?: number
  pattern?: string
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
