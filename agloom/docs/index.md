# Python package (`agloom`)

Build agents that **route themselves** — one `create_agent` call, nine execution patterns, **long-running harness**, memory, streaming, and production guardrails included.

---

## Product pillars

| Pillar | What you get | Start here |
| --- | --- | --- |
| **Auto routing** | [Turn planner](concepts/turn-planner.md) picks one of nine patterns every message | [Execution patterns](concepts/patterns.md) |
| **Long-running harness** | Durable task ledger, verification steps, git tools across sessions | [Harness guide](features/harness.md) |
| **AGP clients** | Same wire protocol for CLI, web, and your custom UI | [Clients overview](guides/clients-overview.md) |
| **Memory & skills** | Session memory always on; `store=` for LTM, skills, quality scoring | [Memory](features/memory.md) |
| **Production guardrails** | HITL, timeouts, retries, circuit breaker, LangSmith | [Production integration](guides/production.md) |

Not sure which pillar fits your problem? See [Use cases](guides/use-cases.md).

---

## Start here

| Step | Guide |
| --- | --- |
| Why teams pick agloom | [Why agloom?](getting-started/why-agloom.md) |
| Install & API keys | [Installation](getting-started/installation.md) |
| First working agent | [Quick start](getting-started/quickstart.md) |
| **From LangChain `create_agent`** | **[LangChain → agloom](guides/migration-from-langchain.md#from-langchain-create_agent)** |
| How a turn flows | [How it works](concepts/how-it-works.md) |

---

## Build features

### Core

| Topic | Guide |
| --- | --- |
| Multi-session coding & RCA | [Long-running harness](features/harness.md) |
| Tools & ReAct loops | [Tool calling](features/tools.md) |
| Conversation memory | [Memory](features/memory.md) |
| Live UIs | [Streaming & events](features/streaming.md) · [Thinking & reasoning](features/thinking-events.md) |
| Approvals | [Human-in-the-loop](features/hitl.md) |
| External tool servers | [MCP servers](features/mcp.md) |

### Extend

| Topic | Guide |
| --- | --- |
| Skills that improve | [Skill learning](features/skills.md) |
| Quality over time | [Feedback & evaluation](features/feedback.md) |
| Batch / fixed routing | [Frozen agents](features/frozen-agents.md) |
| Recursive recovery | [Recursive orchestration](features/orchestration.md) |
| Agent-to-agent work | [Task delegation](features/delegation.md) |
| Ship to prod | [Production integration](guides/production.md) |

---

## Concepts & reference

- [Glossary](concepts/glossary.md) · [Turn planner](concepts/turn-planner.md) · [Execution patterns](concepts/patterns.md) · [`create_agent` API](concepts/create-agent.md)
- [All parameters](configuration/parameters.md) · [Errors & warnings](configuration/errors.md)
- [AGP protocol](protocol/agp.md) — wire format for CLI, web, and custom clients

---

## Integrate & scale

- [Integration overview](guides/developer-overview.md) — in-process, streaming, or AGP
- [Configuration contract](guides/developer-overview.md#configuration-contract-single-source-of-truth) — `create_agent` as single source of truth (no agent-tuning env vars)
- [CLI, web & AGP clients](guides/clients-overview.md) — terminal TUI, browser workspace, custom transports
- [LangChain `create_agent` → agloom](guides/migration-from-langchain.md#from-langchain-create_agent) — same `messages` invoke, `ExecutionResult` return
- [Embedding the runtime](guides/embedding-runtime.md) · [AGP from Python](guides/agp-python.md)

**CLI** and **web workspace** have dedicated nav tabs on Read the Docs — they consume the same AGP events your custom client can use.
