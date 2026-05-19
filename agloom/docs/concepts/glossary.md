# Glossary

Short definitions for terms used across agloom, AGP, and the docs. (Wording may vary slightly by page; this is the canonical sense.)

| Term | Meaning |
| ---- | ------- |
| **Turn** | One **user message** through the agent pipeline for a given `thread_id` — classify → pattern run → assistant reply (and optional tools/HITL). Maps to one “chat turn” in session memory. |
| **Run** | Often the **`run_id`** on an `ExecutionResult` / AGP **`message.assistant`** envelope: **one end-to-end invocation** (one turn) for telemetry, feedback, and deduplicated token metrics. Not the same as “LLM call”. |
| **Call** | A **single LLM request** (`invoke` / `ainvoke` / stream chunk) — classifier, ReAct step, summarizer, etc. One turn can include many calls. Token usage on the wire is de-duplicated per turn so repeated accounting across calls does not double-count. |
| **Session** | **AGP / runtime:** the bridge session id on wire envelopes (`session` field). **Memory:** usually the `thread_id` (and optional `user_id`) that scopes conversation history and store namespaces. |
| **Thread** | **`thread_id`:** stable id for conversation continuity (session memory, checkpoints). May mirror AGP `thread` on envelopes. |
| **Checkpoint** | LangGraph persistence snapshot (query, output, steps, **`analysis`**, …) keyed by `thread_id`. Used by `get_state` / `get_history` and to preserve classifier output across `resume()`. |
| **Orchestration** | Optional recursive **pattern dispatch** inside one turn (`max_pattern_depth` ceiling). Off when ceiling is `0`. |
| **Orchestration plan** | Per-turn limits (depth, token/LLM budgets, escalation) from the classifier or complexity heuristics, clamped to `create_agent` ceilings. |
| **Spawn** | One bounded follow-up pattern run inside the same turn, counted against depth and budgets. |

See also: [Recursive orchestration](../features/orchestration.md), [Wire tokens & metric.tokens](../features/wire-tokens.md), and [AGP — Agloom Protocol](../protocol/agp.md).
