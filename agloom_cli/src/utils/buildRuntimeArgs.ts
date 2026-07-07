/** Forward CLI options to ``agloom-runtime serve`` argv (shared with tests). */

export type RuntimeArgsInput = {
  store: string
  storePath?: string
  session?: string
  thread: string
  model?: string
  provider?: string
  apiKeyEnv?: string
  persistApiKeyInSessionMarker?: boolean
  temperature?: number
  topP?: number
  topK?: number
  maxTokens?: number
  frequencyPenalty?: number
  presencePenalty?: number
  mcp?: string[]
  systemPrompt?: string
  systemPromptFile?: string
  memory?: string
  memoryPath?: string
  skillsDir?: string
  summarizerModel?: string
  profile?: string
  sessionMaxTurns: number
  maxTurns?: number
  budgetTokens?: number
  budgetCostUsd?: number
  noCliTools?: boolean
  noHarness?: boolean
  noRequireToolApproval?: boolean
  noShellTool?: boolean
  noNetworkTools?: boolean
  unrestricted?: boolean
  agentStore?: string
  agentStorePath?: string
  cliToolsWorkingDir: string
  llmTimeout?: number
  turnPlannerTimeout?: number
  reactGraphTimeout?: number
  reactRecursionLimit?: number
  maxConcurrent?: number
  maxRetries?: number
  harnessProjectName?: string
  harnessGoal?: string
  enableMemoryTools?: boolean
  passthrough?: string[]
}

export const buildRuntimeArgs = (o: RuntimeArgsInput): string[] => {
  const turns = o.maxTurns ?? o.sessionMaxTurns
  const parts: string[] = []
  parts.push('--store', o.store)
  if (o.store === 'sqlite') {
    parts.push('--store-path', o.storePath ?? '.agloom/agp_events.db')
  }
  if (o.session) parts.push('--session', o.session)
  const tid = o.thread.trim()
  if (tid) parts.push('--thread', tid)
  const modelArg = typeof o.model === 'string' ? o.model.trim() : o.model != null ? String(o.model).trim() : ''
  if (modelArg && modelArg.toLowerCase() !== 'auto') parts.push('--model', modelArg)
  if (o.provider) parts.push('--provider', o.provider)
  if (o.apiKeyEnv) parts.push('--api-key-env', o.apiKeyEnv)
  if (o.persistApiKeyInSessionMarker) parts.push('--persist-api-key-in-session-marker')
  if (o.temperature !== undefined) parts.push('--temperature', String(o.temperature))
  if (o.topP !== undefined && !Number.isNaN(o.topP)) parts.push('--top-p', String(o.topP))
  if (o.topK !== undefined && !Number.isNaN(o.topK)) parts.push('--top-k', String(o.topK))
  if (o.maxTokens !== undefined) parts.push('--max-tokens', String(o.maxTokens))
  if (o.frequencyPenalty !== undefined && !Number.isNaN(o.frequencyPenalty)) {
    parts.push('--frequency-penalty', String(o.frequencyPenalty))
  }
  if (o.presencePenalty !== undefined && !Number.isNaN(o.presencePenalty)) {
    parts.push('--presence-penalty', String(o.presencePenalty))
  }
  for (const m of o.mcp ?? []) {
    parts.push('--mcp', m)
  }
  if (o.systemPrompt) parts.push('--system-prompt', o.systemPrompt)
  if (o.systemPromptFile) parts.push('--system-prompt-file', o.systemPromptFile)
  if (o.memory) parts.push('--memory', o.memory)
  if (o.memoryPath) parts.push('--memory-path', o.memoryPath)
  if (o.skillsDir) parts.push('--skills-dir', o.skillsDir)
  if (o.summarizerModel) parts.push('--summarizer-model', o.summarizerModel)
  if (o.profile) parts.push('--profile', o.profile)
  parts.push('--session-max-turns', String(turns))
  if (o.budgetTokens !== undefined && !Number.isNaN(o.budgetTokens) && o.budgetTokens > 0) {
    parts.push('--budget-tokens', String(Math.floor(o.budgetTokens)))
  }
  if (o.budgetCostUsd !== undefined && !Number.isNaN(o.budgetCostUsd) && o.budgetCostUsd > 0) {
    parts.push('--budget-cost-usd', String(o.budgetCostUsd))
  }
  if (!o.noCliTools) {
    parts.push('--with-cli-tools', '--cli-tools-working-dir', o.cliToolsWorkingDir)
  }
  if (o.noRequireToolApproval) {
    parts.push('--no-require-tool-approval')
  }
  if (o.noShellTool) parts.push('--cli-tools-no-shell')
  if (o.noNetworkTools) parts.push('--cli-tools-no-network')
  if (o.unrestricted) parts.push('--cli-tools-no-sandbox')
  if (o.agentStore) parts.push('--agent-store', o.agentStore)
  if (o.agentStorePath) parts.push('--agent-store-path', o.agentStorePath)
  if (o.noHarness) parts.push('--no-harness')
  if (o.llmTimeout !== undefined && !Number.isNaN(o.llmTimeout)) {
    parts.push('--llm-timeout', String(o.llmTimeout))
  }
  if (o.turnPlannerTimeout !== undefined && !Number.isNaN(o.turnPlannerTimeout)) {
    parts.push('--turn-planner-timeout', String(o.turnPlannerTimeout))
  }
  if (o.reactGraphTimeout !== undefined && !Number.isNaN(o.reactGraphTimeout)) {
    parts.push('--react-graph-timeout', String(o.reactGraphTimeout))
  }
  if (o.reactRecursionLimit !== undefined && !Number.isNaN(o.reactRecursionLimit)) {
    parts.push('--react-recursion-limit', String(Math.floor(o.reactRecursionLimit)))
  }
  if (o.maxConcurrent !== undefined && !Number.isNaN(o.maxConcurrent)) {
    parts.push('--max-concurrent', String(Math.floor(o.maxConcurrent)))
  }
  if (o.maxRetries !== undefined && !Number.isNaN(o.maxRetries)) {
    parts.push('--max-retries', String(Math.floor(o.maxRetries)))
  }
  if (o.harnessProjectName) parts.push('--harness-project-name', o.harnessProjectName)
  if (o.harnessGoal) parts.push('--harness-goal', o.harnessGoal)
  if (o.enableMemoryTools === false) parts.push('--no-memory-tools')
  parts.push(...(o.passthrough ?? []))
  return parts
}
