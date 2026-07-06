# Long-running harness (progress + git)

Ship agents that **remember what “done” means** across sessions — not just what was said last turn.

The **harness** is an optional layer for multi-day coding, incident response, and product work. It gives your agent a durable **task ledger** with verification steps, session bootstrap briefings, and optional **git** helpers — backed by your LangGraph **`store=`** and an on-disk **`agloom-progress.json`** artifact when configured.

!!! note "Library vs `agloom-runtime serve`"
    **`create_agent(..., harness=False)`** is the Python API default — harness tools are opt-in when embedding agloom.
    **`agloom`** / **`agloom-runtime serve`** turn harness **on** whenever a LangGraph agent store is open (default sqlite) unless you pass **`--no-harness`** or set **`harness.enabled: false`** in YAML.

With harness off, agloom still routes every turn through the same **turn planner** and patterns; work lives in memory and checkpoints only. With **`harness=True`** (library) or the runtime default above, you add a project scope, progress tools, and cross-session accountability.

---

## Why teams use it

| Without harness | With harness |
| --- | --- |
| “What were we doing?” every new session | Goal + task list persist on the artifact |
| Implicit progress in chat history | Explicit tasks with pass/fail verification |
| Ad-hoc git in shell | `git_status`, `git_commit`, checkpoint tags via tools |
| One-shot ReAct loops | **HARNESS CURRENT FOCUS** steers each turn toward the active task |

Typical fits: **RCA agents**, **multi-session refactors**, **PM-style delivery**, any workflow where you want the model to **prove** a step before marking it complete.

---

## Quick start

**Requirements:** `store=` + `harness=True` + `harness_metadata=`.

```python
from agloom import create_agent, HarnessMetadata
from langgraph.store.memory import InMemoryStore

agent = await create_agent(
    model=llm,
    store=InMemoryStore(),
    harness=True,
    name="rca-agent",
    harness_metadata=HarnessMetadata(
        project_name="rca-inc-8842",
        goal="Checkout DB latency spike — find root cause",
        init_git=False,
    ),
)

# Turn 1 — planner may seed harness tasks; REACT runs with active-task focus
result = await agent.ainvoke(
    "Investigate checkout latency spike in production",
    thread_id="rca-session-1",
)
print(result.pattern_used, result.output[:200])

# Turn 2 — routes again (e.g. still REACT); ledger persists; focus updates
result = await agent.ainvoke(
    "I found connection pool exhaustion in the logs",
    thread_id="rca-session-1",
)
```

`harness=True` without **`harness_metadata`** or **`store=`** raises **`ValueError`** at construction.

!!! note "Imports"
    `HarnessMetadata`, `Task`, `ProgressTracker`, and `GitSession` are available from **`from agloom import …`** when the harness submodule loads. Git tools require **`git`** on `PATH`.

---

## How a harness turn flows

```text
create_agent(harness=True, harness_metadata=…)
        ↓
[bind] project goal + optional pre-seeded tasks (once per thread)
        ↓
[turn planner] plan_turn / analyze_query — route + optional harness_plan
        ↓
[sync] persist harness_plan (or derive from subtasks) when ledger is empty
        ↓
[inject] HARNESS CURRENT FOCUS → pattern handler + workers
        ↓
[execute] REACT / SUPERVISOR / … + progress & git tools
```

The **turn planner** (implemented in the classifier module) is one LLM call per turn that decides:

- **Which pattern** runs this message (REACT, SUPERVISOR, DIRECT, …)
- **Optional `harness_plan`** — durable tasks for the ledger (usually turn 1)
- **Optional `subtasks`** — this-turn worker routing for multi-agent patterns

These are related but not the same: REACT often has `subtasks = []` while still needing a `harness_plan`.

### Wire events (`progress.step`)

| Phase | Example detail |
| --- | --- |
| After bind, no tasks | `Harness bound · no tasks yet — turn planner may add tasks after triage` |
| After bind, tasks exist | `Harness ready · N task(s) · X% complete` |
| After plan sync | `Harness planned · N task(s) · …` |

For task-board UIs, also consume **`harness.synced`** (full ledger snapshot) and **`pattern.classified.harness_plan`** (planner output). See [AGP protocol](../protocol/agp.md).

---

## `HarnessMetadata` fields

| Field | Purpose |
| --- | --- |
| `project_name` | Artifact scope key (incident id, effort name) |
| `goal` | North-star objective on the progress artifact |
| `init_git` | Run `git init` once when cwd is not a repo |
| `allow_replan` | When `True`, later turns may **append** new `harness_plan` tasks (duplicate ids skipped) |
| `force_plan` | When `True`, skip short-query heuristics so seeding works on brief intentional messages |
| `tasks` | Optional integrator pre-seed (tickets, alerts) — skipped if artifact already has tasks |

```python
HarnessMetadata(
    project_name="rca-inc-8842",
    goal="Checkout DB latency spike",
    init_git=False,
    allow_replan=False,
    force_plan=False,
    tasks=[
        {
            "id": "ctx-001",
            "description": "Collect alert timeline",
            "priority": "critical",
            "verification_steps": ["Timeline documented with UTC timestamps"],
        },
    ],
)
```

### Planner gating (`needs_plan` / `needs_replan`)

| Gate | When active |
| --- | --- |
| **`needs_plan`** | Harness on, **empty** ledger, non-trivial user query → full wire schema + HARNESS RULE in prompt |
| **`needs_replan`** | `allow_replan=True`, ledger has tasks, user expands scope → append-only harness fields |

Turn 2+ on a seeded ledger uses a **lighter wire schema** (no `harness_plan` fields) unless replan is triggered — saving tokens and avoiding redundant planning.

---

## Progress & git tools

When harness is active, agloom appends **progress + git tools** to the agent:

| Tool | Role |
| --- | --- |
| `bootstrap_progress` | Session start briefing — call at the beginning of each session |
| `get_next_task` | Claim highest-priority pending task |
| `update_task` | Mark verification steps, status, notes |
| `save_progress` | Persist artifact to store + disk |
| `add_task` | Add ad-hoc tasks mid-flight |
| `git_status` / `git_log` / `git_diff` | Inspect repo state |
| `git_commit` / `git_checkpoint` | Commit work with harness-friendly messages |
| `initialize_project` | Manual recovery initializer (normal path uses metadata + planner) |

The agent receives **HARNESS CURRENT FOCUS** in its handler input (active task, verification steps, completion ratio). Multi-worker patterns also prepend this focus to each worker task.

---

## Harness + frozen agents

**Frozen** mode classifies once and replays the locked pattern on later calls. Harness still works:

- **First frozen call** — harness metadata is included in the lock classify; ledger seeds from `harness_plan`
- **Replay turns** — progress context + execution focus refresh; pattern routing is not re-run

See [Frozen agents](frozen-agents.md) for batch translation and fixed-workflow use cases.

---

## Harness + interactive frontends

| How you run agloom | Harness toggle | UI surface |
| --- | --- | --- |
| **Your Python app** | `harness=True` + `harness_metadata` on `create_agent` | `astream_agp_events` → `harness.synced` |
| **`agloom` CLI** | On when store is open (default) | Metrics sidebar; `/checkpoint`, `/git status`, `/diff` |
| **`agloom_web`** | Same runtime default | Header **harness on/off** badge; **Harness** tab for task ledger |
| **`agloom-runtime serve`** | On when store is open (unless `--no-harness`) | AGP events for any client |

### CLI (terminal)

```bash
agloom -m groq:llama-3.3-70b-versatile
# runtime.ready → harness_enabled: true (when store open)
# pattern.classified → harness_plan on planning turns
# harness.synced → full ledger snapshot
```

Slash commands when harness is on: `/checkpoint`, `/diff`, `/hint`, `/git status`, `/git checkpoints`.  
Docs: [CLI — MCP, memory & harness](../../agloom_cli/mcp-memory-harness.md) · [Interactive UI](../../agloom_cli/interactive.md)

### Web workspace

```text
┌─────────────────────────────────────────────────────────────┐
│  Session header          harness on │ tokens ↑↓             │
├──────────────────────────┬──────────────────────────────────┤
│  Chat + tool traces      │  Runtime panel tabs:               │
│  progress.step lines     │  Graph │ Workers │ Trace │        │
│  (Harness bound, …)      │  Harness │ Artifacts              │
└──────────────────────────┴──────────────────────────────────┘
```

The **Harness** tab renders `harness.synced` tasks (active task, verification, completion %).  
Docs: [Web overview](../../agloom_web/index.md) · [Web architecture](../../agloom_web/architecture.md)

### Wire events (all clients)

| Event | Use |
| --- | --- |
| `runtime.ready.harness_enabled` | Badge before first invoke |
| `pattern.classified.harness_plan` | Ledger preview after planner |
| `harness.synced` | Full task board snapshot |
| `command.harness.git` | Git ops from CLI/web slash commands |
| `progress.step` (`harness_init`) | Infra setup line in chat trace |

Details: [AGP protocol](../protocol/agp.md#harness-on-the-wire).

---

## Concurrency

A single `UnifiedAgent` instance **serializes** full turns (`_prepare_turn` → `run_fresh`) with an internal asyncio lock. Per-turn harness focus lives in isolated `invoke_config` state so overlapping `ainvoke` / `astream` calls on the **same instance** do not corrupt each other.

For true parallel throughput across users, use **separate agent instances** or an external job queue.

---

## API reference (integrators)

| Symbol | Role |
| --- | --- |
| `HarnessMetadata` | Project contract at `create_agent` |
| `plan_turn` / `analyze_query` | Turn planner LLM call (`analyze_query` is the legacy alias) |
| `TurnPlan` | Alias for `QueryAnalysis` on `result.analysis` |
| `needs_harness_plan` | Seed gate heuristic |
| `sync_harness_from_analysis` | Persist planner output to artifact |
| `seed_harness_tasks` | Programmatic pre-seed |

---

## Related

- [Turn planner](../concepts/turn-planner.md) — `harness_plan` vs `subtasks`
- [Clients overview](../guides/clients-overview.md) — CLI, web, custom AGP
- [All parameters](../configuration/parameters.md) — `harness`, `harness_metadata`
- [Memory & store](memory.md) — `store=` prerequisite
- [How it works](../concepts/how-it-works.md) — full turn pipeline
- [Thinking events](thinking-events.md) — `harness_init` on the wire
