# MCP, memory & harness

This page covers **three optional layers** exposed through **`agloom-runtime`**: MCP servers, session/long-lived storage defaults, and the **harness** tools around progress + git.

## MCP servers

Pass MCP definitions from the CLI:

```bash
agloom --mcp fs:/abs/path/mcp/filesystem.yaml
```

YAML merges into **`MCPServerConfig`** (Python). In **`agloom.yaml`** use either strings (`name:path`) or objects with `name` + `config` keys; relative paths resolve against the YAML file directory.

**Catalog & specs:** see [MCP Servers](../agloom/features/mcp.md) and the upstream [MCP registry](https://github.com/modelcontextprotocol/servers).

!!! tip "HTTP transport"
    Prefer **`transport: streamable_http`** (or **`http`**, which Agloom maps to the same adapter transport) for modern remote MCP servers. If you configure **`sse`** and connect fails, the runtime retries once with `streamable_http`. Connect errors include server name, URL, transport, and the root cause.

### Listing servers and tools in the CLI

| Method | What you get |
| ------ | ------------ |
| **`/mcp`** slash command | Instant list in **Wire notes** (from last `runtime.mcp.servers` event): server name, ok/fail, each tool name + description when available |
| **Metrics sidebar** (`/stats`) | MCP section with server status and tool preview |
| **Ask the agent** | Should use bundled **`list_mcp_servers`** or the MCP appendix in `system_prompt` — **not** agsuperbrain `list_modules` (that opens the graph DB) |

After MCP connect, the runtime appends tool names + descriptions to the agent instructions and emits **`runtime.mcp.servers`** with a **`tool_catalog`** array per server.

Example skeleton:

```yaml
name: demo-fs
transport: stdio
command: npx
args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

## Session memory

Runtime flags (`serve`):

| Flag                   | Role                                             |
| ---------------------- | ------------------------------------------------ |
| `--memory <type>`      | Backend hint (`sqlite`, `in-memory`, `none`, …). |
| `--memory-path <path>` | SQLite file when using sqlite session memory.    |
| `--session-max-turns`  | Rolling window size.                             |
| `--summarizer-model`   | Separate model id for summarization.             |
| `--no-auto-summarize`  | Disable rolling summarization.                   |

Defaults integrate with LangGraph stores opened by the Python runtime process.

## LangGraph store & harness

Separate from AGP EventStore:

| Flag                        | Role                                                                              |
| --------------------------- | --------------------------------------------------------------------------------- |
| `--agent-store <type>`      | Long-lived agent store (skills, LT memory tools). Default sqlite async.           |
| `--agent-store-path <path>` | SQLite path (default `.agloom/graph_store.sqlite`).                               |

### What is the harness?

The harness is a **cross-session task management system** built into the runtime. It helps the agent maintain accuracy and progress across **long-running**, **multi-turn**, or **multi-session** goals — without losing context or repeating work.

Think of it as a structured "scratchpad" that the agent reads and writes on every turn, so it always knows:

- **Where am I?** (which task is active)
- **What have I done?** (completed tasks, verification results)
- **What's next?** (pending tasks with priority)
- **Is the codebase healthy?** (git status + checkpoints)

### Why it is needed

- **Without harness:** An agent may fix one bug, then in the next turn forget what it was doing and break something else. It has no durable memory of task progress across sessions.
- **With harness:** The agent reads the **progress artifact** before each turn, updates it after each task, and uses git checkpoints to revert if something goes wrong. Accuracy compounds instead of degrading.

The harness solves the "agent forgetfulness" problem for anything longer than a single prompt-response.

### How it is enabled (default: ON)

Under the hood the runtime always does **`create_agent(..., harness=…)`**. When you embed agloom in Python, pass **`harness=True`** yourself — env vars are **not** consulted.

For **`agloom`** / **`agloom-runtime serve`**, harness is **on by default** whenever a LangGraph store is open (default SQLite at `.agloom/graph_store.sqlite`). To turn it off (e.g. RCA):

- **`agloom --no-harness`** or **`agloom-runtime serve --no-harness`** (preferred)
- Optional before spawn: **`AGLOOM_HARNESS=0`** or **`AGLOOM_HARNESS_ENABLED=0`** (runtime-only; same as `--no-harness`)

To confirm: when you run `agloom`, the boot logs will say:

```text
[agloom-runtime] agent LT store=sqlite harness=on
```

### How it manages long-running tasks

The harness injects **11 tools** that form a structured workflow:

| Phase             | Tool                 | What it does                                                              |
| ----------------- | -------------------- | ------------------------------------------------------------------------- |
| **Init**          | `initialize_project` | Decompose a high-level goal into structured tasks with verification steps |
| **Session start** | `bootstrap_progress` | Read current progress and suggest the next task for this session          |
| **Tracking**      | `save_progress`      | Persist progress notes + artifact snapshot to store + disk                |
|                   | `get_next_task`      | Claim the next `PENDING` task for the current session                     |
|                   | `update_task`        | Mark task as `PASSING`/`FAILING`/`IN_PROGRESS` with notes                 |
|                   | `add_task`           | Insert a new task mid-session when discovery happens                      |
| **Git**           | `git_status`         | Working tree summary (branch, clean/dirty, staged/unstaged counts)        |
|                   | `git_log`            | Recent commit history                                                     |
|                   | `git_commit`         | Stage all + commit with a message                                         |
|                   | `git_checkpoint`     | Create a named annotated tag for recovery                                 |
|                   | `git_revert_hint`    | When the tree is broken, suggest how to revert                            |

### Typical flow

```text
1. User: "Build a login system"
2. Agent calls initialize_project → creates tasks:
   [T1] Design DB schema  [PENDING]
   [T2] Build auth routes  [PENDING]
   [T3] Write tests        [PENDING]
3. Agent calls get_next_task → claims T1
4. Agent implements T1, calls update_task → marks PASSING
5. Agent commits via git_commit ("feat: add user schema")
6. Crashes / session ends / new session starts
7. Next session: bootstrap_progress shows T1=PASSING
8. Agent picks T2 — never loses context
```

### Storage

- **Long-term store:** progress data lives in the LangGraph store under the `("harness", "progress")` namespace
- **Disk mirror:** the agent can write `agloom-progress.json` for human inspection alongside LTS
- **Git:** checkpoints create annotated tags (not branches) so they don't interfere with normal git workflow

### Notes

With a default LangGraph store, harness is on unless you pass **`--no-harness`** (or the runtime env overrides above). Library embedders control it only via **`create_agent(..., harness=...)`**.

## SQLite defaults

Typical workspace artifacts:

| Path                            | Purpose                                                                       |
| ------------------------------- | ----------------------------------------------------------------------------- |
| `.agloom/graph_store.sqlite`    | LangGraph async store (default)                                               |
| `.agloom/session_memory.sqlite` | Session memory when `--memory sqlite`                                         |
| `.agloom/skills`                | Default skills disk mirror when `--skills-dir` is omitted                     |
| `.agloom/agp_events.db`         | AGP EventStore when `--store sqlite` (CLI default)                            |

Learned skills are always persisted in the LangGraph store; the mirror directory is for human-readable copies. Tune paths via flags or YAML (`store_path`, `memory_path`, `skills_dir`) plus pass-through **`--`**.

## See also

- [Configuration](config.md)
- [Flags](flags.md)
- [Runtime architecture](../agloom/runtime/architecture.md)
