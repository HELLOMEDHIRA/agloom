# Glossary

Short definitions for terms used across agloom, AGP, and the docs. (Wording may vary slightly by page; this is the canonical sense.)

| Term | Meaning |
| --- | --- |
| **Turn planner** | Per-turn LLM step (`plan_turn` / `analyze_query`) that picks pattern, optional `subtasks`, optional `harness_plan`, and orchestration hints. Implemented in the classifier module; runs **every turn** unless `frozen=True`. |
| **Harness** | Optional cross-session **task ledger** (`harness=True` + `store=` + `harness_metadata`). Progress/git tools + **HARNESS CURRENT FOCUS** steer each turn. |
| **`harness_plan`** | Durable task list from the turn planner, persisted on the progress artifact. Distinct from **`subtasks`** (this-turn worker routing). |
| **`subtasks`** | This-turn worker assignments for SUPERVISOR, SWARM, etc. May be empty while `harness_plan` still seeds REACT focus. |
| **Turn** | One **user message** through the agent pipeline for a given `thread_id` — turn planner → pattern run → assistant reply (and optional tools/HITL). Maps to one “chat turn” in session memory. |
| **Run** | Often the **`run_id`** on an `ExecutionResult` / AGP **`message.assistant`** envelope: **one end-to-end invocation** (one turn) for telemetry, feedback, and deduplicated token metrics. Not the same as “LLM call”. |
| **Call** | A **single LLM request** (`invoke` / `ainvoke` / stream chunk) — turn planner, ReAct step, summarizer, etc. One turn can include many calls. Token usage on the wire is de-duplicated per turn so repeated accounting across calls does not double-count. |
| **Session** | **AGP / runtime:** the bridge session id on wire envelopes (`session` field). **Memory:** usually the `thread_id` (and optional `user_id`) that scopes conversation history and store namespaces. |
| **Thread** | **`thread_id`:** stable id for conversation continuity (session memory, checkpoints). May mirror AGP `thread` on envelopes. |
| **Checkpoint** | LangGraph persistence snapshot (query, output, steps, **`analysis`**, …) keyed by `thread_id`. Used by `get_state` / `get_history` and to preserve turn planner output across `resume()`. |
| **Orchestration** | Optional recursive **pattern dispatch** inside one turn (`max_pattern_depth` ceiling). Off when ceiling is `0`. |
| **Orchestration plan** | Per-turn limits (depth, token/LLM budgets, escalation) from the turn planner or complexity heuristics, clamped to `create_agent` ceilings. |
| **Spawn** | One bounded follow-up pattern run inside the same turn, counted against depth and budgets. |
| **MCP inventory** | agloom session catalog of connected MCP servers and tools (`_mcp_server_rows`, system prompt appendix, `runtime.mcp.servers`, `list_mcp_servers`) — not the Super-Brain graph DB. |
| **MCP appendix** | Block appended to `system_prompt` after connect (`=== MCP servers and tools ===`) listing tool names and descriptions. |
| **Thinking trace** | Routing rationale and reflections on the stream (`thinking` / `thinking.step`, `classify` / `pattern.classified`). |
| **Progress trace** | Infrastructure setup lines (`progress` / `progress.step`) — classify spinner, harness init, skills seed — not model chain-of-thought. |
| **Reasoning tokens** | Provider-native reasoning text on the stream (`token` / `token.delta` with `role=reasoning`), separate from the final answer. |

See also: [Long-running harness](../features/harness.md), [Thinking trace & reasoning streams](../features/thinking-events.md), [Recursive orchestration](../features/orchestration.md), [Wire tokens & metric.tokens](../features/wire-tokens.md), and [AGP — Agloom Protocol](../protocol/agp.md).
