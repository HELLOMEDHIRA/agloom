# Recursive orchestration (self-healing execution)

Optional **recursive pattern dispatch** lets agloom spawn follow-up patterns inside a single user turn — for example REACT failure recovery, conflict deliberation, or dynamic HYBRID_DAG nodes — with hard safety limits so runs cannot recurse forever.

**Default:** orchestration is **off** (`max_pattern_depth=0`). Existing agents behave exactly as before until you opt in.

## Mental model

| Layer | Who decides | What it controls |
| ----- | ----------- | ---------------- |
| **Classifier** (`analyze_query`) | LLM per turn | Pattern, complexity, subtasks, optional **orchestration plan** fields |
| **Agent config** (`create_agent`) | You | **Ceilings** (max depth, tokens, LLM calls) and whether escalation is allowed |
| **Runtime** (`dispatch_pattern`) | Code | Cycle detection, budget checks, spawn/escalate, LLM evaluation |

Think of orchestration as a **safety net and observability layer**, not a replacement for the nine execution patterns. The classifier still picks the primary pattern; orchestration may add bounded follow-up work when enabled.

## Enabling orchestration

Set a **non-zero ceiling** on depth. The classifier (or complexity heuristics) picks the **actual** depth per turn, clamped to your ceiling.

```python
from agloom import create_agent

agent = await create_agent(
    model=llm,
    name="orchestrated-agent",
    max_pattern_depth=5,              # ceiling (0 = off)
    max_orchestration_tokens=100_000,  # 0 = unlimited
    max_orchestration_llm_calls=80,
    enable_auto_escalation=True,      # allow follow-up spawns when eval says so
    orchestration_plan_from_classifier=True,  # per-turn plan (default)
)
```

With `max_pattern_depth=0`, no recursive dispatch runs and classifier orchestration fields are ignored.

### Static vs per-turn limits

| `orchestration_plan_from_classifier` | Behavior |
| ------------------------------------ | -------- |
| `True` (default) | Classifier (or complexity-derived defaults) sets depth, token/LLM budgets, and escalation hint **per turn**, clamped to agent ceilings. Simple queries (complexity 0–2) typically get depth `0` even when the ceiling is `5`. |
| `False` | Legacy mode: use agent ceilings directly every turn (`max_pattern_depth` is the active depth, not just a cap). |

## Classifier orchestration fields

When the classifier runs, it may return optional fields on `QueryAnalysis` (wire names are strings in tool JSON):

| Field | Purpose |
| ----- | ------- |
| `orchestration_depth` | Suggested max recursive depth for this turn |
| `orchestration_token_budget` | Suggested total orchestration token budget |
| `orchestration_llm_call_budget` | Suggested max orchestration LLM calls |
| `orchestration_auto_escalation` | `"true"` / `"false"` — hint for follow-up spawns |

Empty or omitted fields fall back to **complexity-derived defaults** (e.g. complexity ≤2 → depth 0; complexity 9–10 → depth up to 4 and escalation hint on).

`enable_auto_escalation` on the agent is a **master switch**: the turn only auto-escalates when both the agent allows it and the per-turn plan requests it.

## Safety (hard stops)

These limits apply regardless of classifier output:

- **Depth** — `current_depth >= max_depth` → `OrchestrationBudgetExceeded`
- **Cycles** — same `(pattern, task_hash)` on the ancestor chain, or three identical spawns in a row → `OrchestrationCycleDetected`
- **Token / LLM call budgets** — tracked on `OrchestrationContext` when ceilings are > 0
- **Timeout decay** — per-depth LLM timeout shrinks (`apply_timeout`)

## Evaluation and escalation

After each `dispatch_pattern` step:

1. **LLM evaluation** runs when `enable_orchestration_llm_eval=True` (default). Each step gets `confidence` and `quality_score` on the orchestration trace and AGP `orchestration.step` events.
2. **Auto-escalation** runs only when `enable_auto_escalation=True` **and** the per-turn plan has `auto_escalation=True`. Rules in `escalation_rules` (`default`, `conservative`, `aggressive`) map evaluation signals to follow-up patterns (e.g. low confidence → REFLECTION, conflicts → SWARM).

Set `enable_orchestration_llm_eval=False` for a minimal structural fallback only (no extra LLM call per step).

Conflict detection for SWARM/BLACKBOARD spawn hints uses the **LLM eval** path, not token-overlap heuristics.

## Pattern integrations

When orchestration is on and `enable_pattern_spawns=True` (default):

| Pattern | Behavior |
| ------- | -------- |
| **REACT** | Failed run may spawn REFLECTION recovery |
| **SUPERVISOR** | Failed workers may recover; optional per-worker `dispatch_pattern` when `enable_supervisor_worker_dispatch=True` |
| **SWARM / BLACKBOARD** | LLM-detected conflicts may spawn deliberation |
| **HYBRID_DAG** | Nodes with **tools** or parent `complexity >= 7` may reclassify and dispatch sub-patterns when `enable_dynamic_dag_nodes=True` |
| **Sequential (planner)** | High-complexity steps may use dynamic dispatch |

## Observability

- **Metadata:** `result.metadata["orchestration_trace"]` and `orchestration_turn_plan` (effective depth, budgets, `source`).
- **AGP:** `orchestration.step` events with `depth`, `pattern`, `action`, `confidence`, `quality_score`. See [AGP — orchestration.step](../protocol/agp.md#orchestrationstep).
- **CLI:** confidence shown as `conf=XX%` on orchestration trace lines when present.

## `OrchestrationRuntime` (advanced)

For custom integrations, `agloom.orchestrator.OrchestrationRuntime` wraps `dispatch_pattern`, `fresh_orchestration_context`, and `resolve_turn_orchestration`:

```python
from agloom.orchestrator import OrchestrationRuntime, resolve_turn_orchestration

rt = OrchestrationRuntime(agent.config)
plan = resolve_turn_orchestration(agent.config, analysis)
if plan.max_depth > 0:
    ...
```

## Related

- [All parameters — orchestration](../configuration/parameters.md#recursive-orchestration)
- [How it works](../concepts/how-it-works.md)
- [Execution patterns](../concepts/patterns.md)
- [Streaming & events](streaming.md)
