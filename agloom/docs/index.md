# Python package (`agloom`)

Build agents that **route themselves** — one `create_agent` call, nine execution patterns, memory, streaming, and production guardrails included.

---

## Start here

| Step | Guide |
| ---- | ----- |
| Why teams pick agloom | [Why agloom?](getting-started/why-agloom.md) |
| Install & API keys | [Installation](getting-started/installation.md) |
| First working agent | [Quick start](getting-started/quickstart.md) |
| How a turn flows | [How it works](concepts/how-it-works.md) |

---

## Build features

| Topic | Guide |
| ----- | ----- |
| Tools & ReAct loops | [Tool calling](features/tools.md) |
| Conversation memory | [Memory](features/memory.md) |
| Live UIs | [Streaming & events](features/streaming.md) |
| Approvals | [Human-in-the-loop](features/hitl.md) |
| Skills that improve | [Skill learning](features/skills.md) |
| Quality over time | [Feedback & evaluation](features/feedback.md) |
| Ship to prod | [Production integration](guides/production.md) |

---

## Concepts & reference

- [Glossary](concepts/glossary.md) · [Execution patterns](concepts/patterns.md) · [`create_agent` API](concepts/create-agent.md)
- [All parameters](configuration/parameters.md) · [Errors & warnings](configuration/errors.md)
- [AGP protocol](protocol/agp.md) — wire format for CLI, web, and custom clients

---

## Integrate & scale

- [Integration overview](guides/developer-overview.md) — in-process, streaming, or AGP
- [Embedding the runtime](guides/embedding-runtime.md) · [AGP from Python](guides/agp-python.md)
- [Recursive orchestration](features/orchestration.md)

**CLI** and **web workspace** are documented in the main site nav — they consume the same AGP events your custom client can use.

