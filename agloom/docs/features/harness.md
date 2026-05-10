# Long-running harness (progress + git)

The **harness** is an **optional** layer in the **`agloom`** library. It helps agents work across many sessions on the same codebase or product goal: structured **tasks**, **verification steps**, **bootstrap briefings**, and **git** helpers — backed by your LangGraph **store** and optional **`agloom-progress.json`** on disk.

You can turn it on from **`create_agent`** or from the **agloom CLI** (see below). In both cases it only takes effect when a **`store`** is in use — without a store, `harness=True` is **ignored** and a warning is logged.

## When to use it

- Multi-session coding or PM-style agents where you want a **durable task list** and explicit **pass/fail verification** before marking work done.
- Flows where the model should **commit**, **tag checkpoints**, or **inspect git status** through tools instead of raw shell (still **trusted** use — same caution as any git automation).

## Enabling the harness (library)

Requirements:

1. Pass **`store=`** — any LangGraph-compatible store (`InMemoryStore`, `AsyncSqliteStore`, etc.).
2. Pass **`harness=True`**.
3. Optionally set **`harness_project_name=`** (default `"project"`). This scopes the progress artifact key: one **ProgressTracker** singleton per `(agent_name, harness_project_name)`.

```python
from agloom import create_agent
from langgraph.store.memory import InMemoryStore

async def main():
    agent = await create_agent(
        model=llm,
        store=InMemoryStore(),
        harness=True,
        harness_project_name="my-app",
        name="coder",
    )
```

## Harness + interactive frontends

When you use the **agloom CLI** (`agloom_cli/`) or your own driver, enable the harness through **`agloom.yaml`** (or `create_agent(..., harness=True, …)` in code).

Typical behaviour with a project-local `.agloom/` layout:

- **SQLite store:** `graph_store.sqlite` holds harness / skills durable state when a store is configured.
- **Memory / checkpoints:** depend on your YAML and whether you pass a LangGraph checkpointer — mirror the same settings you would use for a pure-library deployment.

- **Off:** set `harness.enabled: false` or `AGLOOM_HARNESS=0`.
- **On:** `harness.enabled: true` or `AGLOOM_HARNESS=1`.
- **Scoping:** optional `harness.project_name` maps to `harness_project_name` when non-empty.

## What gets injected

When the harness is active, **11 tools** are appended to your tool list:

| Tool | Role |
|------|------|
| `initialize_project` | First-run decomposition: goal → structured task list + briefing (uses the agent LLM + store). |
| `bootstrap_progress` | Session start protocol: context, task list, suggested next task. |
| `save_progress` | Persist progress notes and artifact snapshot (LTS + disk when configured). |
| `get_next_task` | Claim the next pending task for the current session. |
| `update_task` | Update status, notes, errors, verification results. |
| `add_task` | Add a task with optional verification steps. |
| `git_status` | Working tree summary. |
| `git_log` | Recent commits. |
| `git_commit` | Stage all and commit with a message. |
| `git_checkpoint` | Named checkpoint (tag-style) for recovery. |
| `git_revert_hint` | Suggest recovery when the tree is broken. |

Implementations live under `agloom/harness/` (`progress.py`, `git.py`, `initializer.py`).

## How the agent “sees” progress

On each turn (non-frozen path), the unified agent may prepend a **cross-session progress** block built from the live artifact (`ProgressTracker.get_classifier_context()`), under a heading like `=== CROSS-SESSION PROGRESS ===`, so the **classifier** and downstream patterns stay aligned with the current task graph.

Per-session bootstrap also runs **`ProgressTracker.bootstrap(...)`** when harness is enabled so the artifact is tied to the effective **`thread_id`**.

## Storage and disk

- **Long-term store**: Namespace `("harness", "progress")` is used for the artifact and session bootstrap metadata (see `agloom/harness/progress.py`).
- **Disk mirror**: Tools can write **`agloom-progress.json`** (see `write_to_disk` in the tracker) for human inspection or recovery alongside LTS.

## Related

- [All Parameters](../configuration/parameters.md) — `harness`, `harness_project_name`
- [The create_agent API](../concepts/create-agent.md)
- [Memory & store](memory.md) — `store=` prerequisite
