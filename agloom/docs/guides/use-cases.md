# Use cases

Map your problem to the right agloom feature — then follow the linked guide.

---

## Chatbot with session memory

**You need:** Multi-turn Q&A that remembers context within a conversation.

| Use | Guide |
| --- | --- |
| Pass `thread_id` on every call | [Quick start](../getting-started/quickstart.md#conversation-memory) |
| How memory is injected | [Memory](../features/memory.md) |
| Wire events for UIs | [Streaming & events](../features/streaming.md) |

---

## Tool agent (search, code, APIs)

**You need:** An agent that calls tools in a loop until the task is done.

| Use | Guide |
| --- | --- |
| Define LangChain `@tool` functions | [Tool calling](../features/tools.md) |
| Automatic REACT routing | [Turn planner](../concepts/turn-planner.md) · [Patterns](../concepts/patterns.md) |
| Risky tools need approval | [Human-in-the-loop](../features/hitl.md) |

---

## Multi-day coding, RCA, or delivery

**You need:** A task ledger that survives sessions, verification steps, and optional git checkpoints.

| Use | Guide |
| --- | --- |
| Python: `harness=True` + `HarnessMetadata` | [Long-running harness](../features/harness.md) |
| CLI: harness on by default with store | [CLI — MCP, memory & harness](../../agloom_cli/mcp-memory-harness.md) |
| Web: Harness tab + git slash commands | [Web workspace](../../agloom_web/index.md) |
| Runnable example | [Harness example](../examples/python-examples.md) |

---

## Batch processing with fixed routing

**You need:** Classify once, run thousands of similar inputs through the same pattern topology.

| Use | Guide |
| --- | --- |
| `frozen=True` on `create_agent` | [Frozen agents](../features/frozen-agents.md) |
| Combine with harness ledger | [Harness + frozen](../features/harness.md#harness--frozen-agents) |

---

## Custom chat UI or Slack bot

**You need:** Stream tokens, tool calls, and thinking steps in your own frontend.

| Use | Guide |
| --- | --- |
| In-process events | [Streaming](../features/streaming.md) · [Thinking trace](../features/thinking-events.md) |
| Typed wire protocol | [AGP specification](../protocol/agp.md) |
| Shared runtime for multiple clients | [Clients overview](clients-overview.md) |

---

## Platform team / shared agent service

**You need:** One runtime, many clients, production deployment.

| Use | Guide |
| --- | --- |
| `agloom-runtime serve` | [Runtime architecture](../runtime/architecture.md) |
| Docker, TLS, observability | [Production deployment](deployment.md) |
| FastAPI embedding | [Production integration](production.md) |

---

## Agents that improve over time

**You need:** Reuse successful patterns and score quality across runs.

| Use | Guide |
| --- | --- |
| Skill extraction + injection | [Skill learning](../features/skills.md) |
| Auto-eval + user feedback | [Feedback & evaluation](../features/feedback.md) |
| Requires `store=` | [Memory](../features/memory.md) |

---

## Complex multi-step recovery

**You need:** Bounded follow-up patterns when quality checks fail mid-turn.

| Use | Guide |
| --- | --- |
| `max_pattern_depth` + auto-escalation | [Recursive orchestration](../features/orchestration.md) |
| Planner sets per-turn budgets | [Turn planner](../concepts/turn-planner.md) |

---

## External tools via MCP

**You need:** Connect filesystem, Grafana, databases, or custom MCP servers.

| Use | Guide |
| --- | --- |
| MCP server config | [MCP servers](../features/mcp.md) |
| CLI MCP flags | [CLI config](../../agloom_cli/config.md) |

---

## LangChain migration

**You need:** Same `messages` invoke shape, richer return type and auto-routing.

| Use | Guide |
| --- | --- |
| Side-by-side comparison | [Why agloom?](../getting-started/why-agloom.md) |
| Porting checklist | [LangChain → agloom](migration-from-langchain.md) |
