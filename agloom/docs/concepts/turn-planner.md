# Turn planner

Every user message passes through the **turn planner** before any execution pattern runs. You never write routing code — agloom picks DIRECT vs REACT vs SUPERVISOR (and six other patterns) per turn.

The planner is implemented in the classifier module. Public names:

| Name | Role |
| --- | --- |
| `plan_turn` | Primary function |
| `analyze_query` | Legacy alias (same behavior) |
| `QueryAnalysis` / `TurnPlan` | Structured result on `result.analysis` |

---

## What the planner decides

On each turn (unless `frozen=True` replays a locked plan), one bounded LLM call returns:

| Field | Purpose |
| --- | --- |
| **`pattern`** | Which of the nine execution patterns runs (DIRECT, REACT, SUPERVISOR, …) |
| **`complexity`** | Rough difficulty score (1–10) for logging and UI |
| **`reasoning`** | Short rationale (also on wire as `thinking.step`) |
| **`subtasks`** | This-turn worker assignments for multi-agent patterns |
| **`harness_plan`** | Durable tasks for the long-running harness ledger (when harness is on) |
| **`harness_work_kind`** | Short label (`investigation`, `implementation`, …) for harness UIs |
| **Orchestration hints** | Per-turn depth/budget when recursive orchestration is enabled |

**`subtasks`** and **`harness_plan`** are related but not the same:

- **`subtasks`** — parallel workers *this turn* (SUPERVISOR, SWARM, …)
- **`harness_plan`** — cross-session task ledger persisted to the progress artifact

REACT often has `subtasks = []` while still needing a `harness_plan` on turn 1.

---

## Where you see the decision

| Surface | Location |
| --- | --- |
| In-process | `result.pattern_used`, `result.analysis` |
| Logs | `[Graph:classify]` / classify events |
| AGP wire | `thinking.step` (`step: analyze_query`), then `pattern.classified` |
| Harness UIs | `pattern.classified.harness_plan`, then `harness.synced` after sync |
| LangSmith | Classify span on every turn |

See [Execution patterns](patterns.md) for what each pattern does after routing.

---

## Configuration

| Parameter | Default | Effect |
| --- | --- | --- |
| `classifier_timeout` | model-dependent | Max seconds for the planner LLM call |
| `turn_planner_timeout` | alias of `classifier_timeout` | Same ceiling (preferred name in new code) |
| `structured_max_retries` | `1` | Retries when structured output parsing fails |
| `fallback_pattern` | `None` | Pattern when planner fails or returns unknown handler |
| `frozen=True` | `False` | Planner runs **once**; later calls replay locked `analysis` |

Full list: [All parameters](../configuration/parameters.md).

---

## Harness interaction

When **`harness=True`** + **`store=`** + **`harness_metadata`**:

1. Planner may emit **`harness_plan`** on turn 1 (or when `allow_replan=True` expands scope)
2. Runtime syncs the plan to `agloom-progress.json` (when configured)
3. **HARNESS CURRENT FOCUS** is injected into the pattern handler

When harness is off, the planner still runs — it just omits durable task seeding.

Details: [Long-running harness](../features/harness.md).

---

## Frozen agents

With **`frozen=True`**, the planner runs on the **first** `ainvoke` only. The locked `analysis` (pattern, subtasks, orchestration limits) replays on every later message. Harness ledger seeding still happens on that first call.

Details: [Frozen agents](../features/frozen-agents.md).

---

## Related

- [How it works](how-it-works.md) — full turn pipeline diagram
- [Glossary](glossary.md) — turn, run, thread, checkpoint
- [AGP protocol](../protocol/agp.md) — `pattern.classified`, `harness.synced`
- [Choosing a pattern](../guides/choosing-a-pattern.md) — conceptual guide (planner does this automatically)
