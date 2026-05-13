# Migrating from raw LangChain agents

You already have **`ChatOpenAI`**, **`create_tool_calling_agent`**, **`AgentExecutor`**, or a LangGraph **prebuilt** graph. Here is a pragmatic port path to **agloom**.

## Mental model

| LangChain building block      | In agloom                                                                                  |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| Manual loop / `AgentExecutor` | Single **`create_agent()`** — patterns chosen per query                                    |
| Tool list                     | Same tools; optional **CLI tools**, MCP, harness tools                                     |
| Memory / checkpoints          | **`memory=`**, **`store=`**, LangGraph checkpointers — see [Memory](../features/memory.md) |
| Streaming callbacks           | **`agent.astream_events`** + AGP translation if you use **`agloom-runtime`**               |

## Step 1 — Swap the shell, keep the brain

1. Keep your **`ChatModel`** construction (keys, `base_url`, extras unchanged).
2. Collect your existing tools into one list.
3. Replace executor wiring with:

```python
from agloom import create_agent

agent = await create_agent(
    model=your_chat_model,
    tools=your_tools,
    name="migrated",
)
result = await agent.ainvoke("Your question here")
```

## Step 2 — Map callbacks

- **`verbose=True`** style tracing → use **streaming** (`astream_events`) or enable **observability** / LangSmith if configured.
- **Interrupts / human approval** → agloom **HITL** (`interrupt_before`, `user_callback`) — see [Human-in-the-Loop](../features/hitl.md).

## Step 3 — Gradually adopt patterns

Start with defaults (**auto pattern**). Once stable, bias routing with **`fallback_pattern`** or YAML **`pattern`** — see [Execution Patterns](../concepts/patterns.md).

## Step 4 — Runtime bridge (optional)

If you serve a UI over **AGP**, run **`agloom-runtime serve`** and point **agloom-cli** or **agloom_web** at it instead of embedding your own loop — same agent instance, standardized wire events ([Protocol](../protocol/agp.md)).

## Common pitfalls

- **Different async entry**: agloom agents are **`await create_agent`** then **`await agent.ainvoke`** — ensure your event loop matches (asyncio).
- **Tool names** must remain stable if you persist allowlists / skills.

## See also

- [Why agloom?](../getting-started/why-agloom.md)
- [LCEL as tools](lcel-as-tools.md)
- [Embedding the runtime](embedding-runtime.md)
