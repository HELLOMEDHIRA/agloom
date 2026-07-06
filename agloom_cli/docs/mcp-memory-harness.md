# MCP, memory & harness

This page covers **three optional layers** exposed through **`agloom-runtime`**: MCP servers, session/long-lived storage defaults, and the **harness** tools around progress + git.

---

## MCP servers

Configure MCP in **`agloom.yaml`** or via runtime flags. The runtime merges MCP tools **before** the turn planner runs on each message.

See [Tools & HITL](tools-hitl.md) and the Python package [MCP guide](../agloom/features/mcp.md).

---

## LangGraph store & harness

### What is the store?

The **LangGraph store** (`--agent-store`, default SQLite at `.agloom/graph_store.sqlite`) backs:

- Long-term memory tools (`save_memory` / `recall_memory`)
- Skill learning and feedback
- Harness progress artifacts (`("harness", "progress")` namespace)

### What is the harness?

The harness is a **cross-session task ledger** built into the runtime. It helps agents maintain accuracy and progress across **long-running**, **multi-turn**, or **multi-session** goals — with explicit verification steps and optional git checkpoints.

- **Without harness:** Work lives in chat history and session memory only.
- **With harness:** The **turn planner** may seed a durable `harness_plan` on the first planning turn; each turn gets **HARNESS CURRENT FOCUS**; progress/git tools update the artifact.

### Enabling harness (runtime)

Under the hood the runtime calls **`create_agent(..., harness=…, harness_metadata=…)`**. When you embed agloom in Python, pass those kwargs yourself — env vars are **not** consulted.

For **`agloom`** / **`agloom-runtime serve`**, harness is **on by default** whenever a LangGraph store is open. To turn it off:

- **`agloom --no-harness`** or **`agloom-runtime serve --no-harness`** (preferred)
- Optional before spawn: **`AGLOOM_HARNESS=0`** or **`AGLOOM_HARNESS_ENABLED=0`**

```text
[agloom-runtime] agent LT store=sqlite harness=on
```

The TUI and web workspace show **`harness=on|off`** on `runtime.ready`.

### How a harness turn flows

```text
bind project (goal + optional pre-seeded tasks)
        ↓
turn planner — route + optional harness_plan
        ↓
sync ledger + inject HARNESS CURRENT FOCUS
        ↓
pattern run + progress/git tools
```

Wire events you may see in the trace:

| Phase | Example `progress.step` detail |
| ----- | ------------------------------ |
| Bound, no tasks yet | `Harness bound · no tasks yet — turn planner may add tasks after triage` |
| Bound, tasks exist | `Harness ready · N task(s) · X% complete` |
| After plan sync | `Harness planned · N task(s) · …` |

### Harness tools (12)

| Tool | Role |
| ---- | ---- |
| `bootstrap_progress` | Session start briefing — read artifact and suggest next task |
| `get_next_task` | Claim highest-priority pending task |
| `update_task` | Mark verification steps and status |
| `save_progress` | Persist to store + optional disk mirror |
| `add_task` | Insert ad-hoc tasks mid-flight |
| `git_status` / `git_log` / `git_diff` | Inspect repo state |
| `git_commit` / `git_checkpoint` | Commit or tag checkpoint |
| `git_revert_hint` | Suggest revert path when the tree is broken |
| `initialize_project` | Manual recovery initializer (normal path uses metadata + turn planner) |

### Typical flow

```text
1. User: "Investigate checkout latency spike"
2. Turn planner seeds harness_plan → tasks on artifact
3. Agent calls bootstrap_progress → sees active task + verification steps
4. Agent implements, calls update_task → marks PASSING
5. Agent commits via git_commit
6. New session: bootstrap_progress shows prior progress; focus updates each turn
```

### Storage

- **Long-term store:** progress under `("harness", "progress")`
- **Disk mirror:** optional `agloom-progress.json` for human inspection
- **Git:** checkpoints use annotated tags

### Notes

With a default LangGraph store, harness is on unless you pass **`--no-harness`**. Library embedders control it via **`create_agent(..., harness=..., harness_metadata=...)`**. See the Python [Long-running harness](../agloom/features/harness.md) guide for `allow_replan`, `force_plan`, and frozen agents.

---

## SQLite defaults

Session memory and the LT store default to SQLite files under **`.agloom/`** in the workspace. See [Configuration](config.md) for paths and overrides.
