# Package developer overview

Most applications only need **Door 1**: import from the top-level **`agloom`** package (`create_agent`, `UnifiedAgent`, pattern types, memory helpers, etc.). That surface is covered throughout this docs tree.

If you are **embedding agloom** in a custom driver (another CLI, a web server, an IDE, or an observability pipeline), you also have stable **submodules** — same SemVer guarantees as the rest of the package, but aimed at integrators rather than day-to-day agent authors.

## Door 1 — `import agloom`

| Goal | Starting points |
|------|------------------|
| Build an agent | [Quick start](../getting-started/quickstart.md), [`create_agent`](../concepts/create-agent.md) |
| Stream tokens / steps | [Streaming & events](../features/streaming.md) (includes **`astream_agp_events`**) |
| Memory, skills, harness | [Memory](../features/memory.md), [Skills](../features/skills.md), [Harness](../features/harness.md) |

## Door 2 — runtime, protocol, observability, LLM

| Module | Role | Guide |
|--------|------|-------|
| **`agloom.runtime`** | AGP bridge (`run_invocation`), local **`RuntimeNode`**, workers, scheduler, registry | [Embedding the runtime](embedding-runtime.md) |
| **`agloom.protocol`** | Typed AGP events, emitters, command parsing, replay stores | [AGP from Python](agp-python.md) |
| **`agloom.observability`** | SQLite-backed store + FastAPI router + SSE replay | [Observability API](observability-python.md) |
| **`agloom.llm`** | Programmatic model resolution (`get_model`, env-key routing) | [LLM resolution](llm-resolution.md) |

Wire-format reference (all event types and commands): [**AGP — Agloom Protocol**](../protocol/agp.md). Deeper runtime wiring (stdio/WebSocket process): [Runtime architecture](../runtime/architecture.md).

## agloom CLI vs library

The interactive **agloom** shell shipped in the repo under **`agloom_cli/`** is a **Node.js** client that speaks AGP over stdio/WebSocket. It is documented under **agloom CLI** in the site nav. It is **not** the PyPI `agloom` wheel; the wheel is the Python library described here.
