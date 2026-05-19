# Migrating from LangChain

agloom is built on LangChain and LangGraph. You keep your models, tools, and (optionally) checkpointers; you swap the agent shell for **`agloom.create_agent`**, which adds classification, nine execution patterns, memory, and production guardrails.

This guide has two paths:

1. **[From LangChain `create_agent`](#from-langchain-create_agent)** — you already use the LangChain v1 agent API (`langchain.agents.create_agent`).
2. **[From older LangChain stacks](#from-older-langchain-stacks)** — `AgentExecutor`, `create_tool_calling_agent`, or a custom LangGraph graph.

---

## From LangChain `create_agent`

LangChain and agloom both expose **`create_agent`** with the same **invoke input** shape. The differences are the **package**, **factory async**, **return type**, and **what runs inside** each turn.

### Side-by-side

| Topic | LangChain `create_agent` | agloom `create_agent` |
| ----- | ------------------------ | --------------------- |
| Import | `from langchain.agents import create_agent` | `from agloom import create_agent` |
| Factory | Sync — returns a compiled graph | **Async** — `agent = await create_agent(...)` (or `create_agent_sync`) |
| Invoke input | `{"messages": [{"role": "user", "content": "..."}]}` | **Same** (+ optional plain `str` sugar) |
| `system_prompt` | Supported at build time | Supported at build time |
| `tools` | LangChain tools | Same tools |
| `model` | Model id string or `BaseChatModel` | Same |
| Return value | Graph state dict (e.g. `result["messages"]`) | **`ExecutionResult`** — use `.output`, `.messages`, `.analysis`, `.run_id` |
| Routing | Fixed tool loop until stop | **Classifier** picks pattern per turn (REACT, SUPERVISOR, DIRECT, …) |
| Streaming | `agent.stream` / `astream` on the graph | **`agent.astream_events`** — tokens + structured events in one stream |
| Session memory | Checkpointer / thread config on the graph | Pass **`thread_id=`** on each `ainvoke` / `astream` (see [Memory](../features/memory.md)) |
| Extra knobs | LangChain middleware on the graph | agloom **`middleware`**, HITL, skills, **`frozen=True`**, orchestration ceilings — see [Parameters](../configuration/parameters.md) |

### Minimal port

**LangChain:**

```python
from langchain.agents import create_agent

agent = create_agent(
    model="openai:gpt-4o",
    tools=[search],
    system_prompt="You are a helpful assistant.",
)

result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "What is the weather in Tokyo?"}]}
)
last_message = result["messages"][-1]
print(last_message.content)
```

**agloom:**

```python
from agloom import create_agent

agent = await create_agent(
    model="openai:gpt-4o",  # or your existing ChatModel instance
    tools=[search],
    system_prompt="You are a helpful assistant.",
    name="assistant",
)

result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "What is the weather in Tokyo?"}]}
)
print(result.output)  # final assistant text
# result.messages — same LangChain message objects as LangChain’s graph state
```

### Reading the result

| LangChain habit | agloom equivalent |
| --------------- | ----------------- |
| `result["messages"][-1].content` | `result.output` or last AI message in `result.messages` |
| Final text only | `result.output` |
| Tool / AI message trail | `result.messages` |
| Which tools / pattern ran | `result.analysis`, `result.pattern_used`, `result.steps` |
| Trace / feedback id | `result.run_id` → `await agent.feedback(result.run_id, "positive")` |

### Invoke and streaming (unchanged input)

```python
# String sugar (agloom only)
await agent.ainvoke("Hello")

# Streaming — prefer astream_events for tokens + lifecycle events
async for event in agent.astream_events(
    {"messages": [{"role": "user", "content": "Hello"}]},
    thread_id="session-1",
):
    if event.type == "token":
        print(event.data.get("content", ""), end="", flush=True)
    elif event.type == "done":
        result = event.data["result"]
```

LangChain’s `agent.astream(..., stream_mode="messages")` maps conceptually to **`astream_events`** or **`result.messages`** after `ainvoke`. See [Streaming](../features/streaming.md).

### Parameters that map directly

These work the same way you expect from LangChain’s agent builder:

- **`model`** — provider string (`"openai:gpt-4o"`) or `BaseChatModel`
- **`tools`** — list of `@tool` / `BaseTool` callables
- **`system_prompt`** — fixed system instructions (string or callable)

Pass a LangGraph **`checkpointer`** if you use graph interrupts and **`agent.resume()`** — agloom persists checkpoints compatible with LangGraph inspection. See [Production — checkpointer](../guides/production.md#checkpointer-state-persistence-and-inspection).

### agloom-only parameters (opt in)

You do **not** need these on day one; add them when you want the behavior:

| Parameter | Purpose |
| --------- | ------- |
| `store=` | Long-term memory, skills, feedback ([Memory](../features/memory.md)) |
| `thread_id` / `user_id` at **call time** | Session and user-scoped memory ([create_agent — identity](../concepts/create-agent.md#identity-resolution)) |
| `interrupt_before` / `user_callback` | Human-in-the-loop ([HITL](../features/hitl.md)) |
| `frozen=True` | Classify once, replay plan for batch jobs ([Frozen agents](../features/frozen-agents.md)) |
| `max_pattern_depth > 0` | Bounded recursive orchestration ([Orchestration](../features/orchestration.md)) |
| `middleware=[...]` | Query/result transforms ([Middleware](../features/middleware.md)) |
| `llm_timeout`, `max_retries`, `rate_limit` | Production reliability ([Reliability](../configuration/reliability.md)) |

### Common pitfalls

1. **Forgetting `await` on the factory** — `create_agent` is async; use `await create_agent(...)` or `create_agent_sync(...)`.
2. **Expecting a graph dict back** — use `ExecutionResult.output` / `.messages`, not `result["messages"]` unless you read `.messages` on the result object.
3. **`user_id` only at build time** — long-term user scope requires `user_id=` on each `ainvoke` / `astream`, not only on `create_agent`.
4. **Assuming a single REACT loop** — agloom may choose DIRECT, SUPERVISOR, PIPELINE, etc. per turn; tools still run when the classifier routes through REACT or worker plans.
5. **Dict invoke without `messages`** — only `{"messages": [...]}`, a plain string, or a multimodal block list are valid; arbitrary dict keys are rejected.

### Sync scripts

```python
from agloom import create_agent_sync

agent = create_agent_sync(model=llm, tools=[search], name="assistant")
result = agent.invoke({"messages": [{"role": "user", "content": "Hi"}]})
```

---

## From older LangChain stacks

You have **`ChatOpenAI`**, **`create_tool_calling_agent`**, **`AgentExecutor`**, or a hand-rolled LangGraph **prebuilt** graph.

### Mental model

| LangChain building block | In agloom |
| ------------------------ | --------- |
| Manual loop / `AgentExecutor` | Single **`create_agent()`** — patterns chosen per query |
| Tool list | Same tools; optional **CLI tools**, MCP, harness tools |
| Memory / checkpoints | **`memory=`**, **`store=`**, LangGraph checkpointers — see [Memory](../features/memory.md) |
| Streaming callbacks | **`agent.astream_events`** + AGP if you use **`agloom-runtime`** |

### Step 1 — Swap the shell, keep the brain

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
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "Your question here"}]}
)
```

### Step 2 — Map callbacks

- **`verbose=True`** style tracing → **streaming** (`astream_events`) or [Observability](../features/observability.md) / LangSmith.
- **Interrupts / human approval** → agloom **HITL** (`interrupt_before`, `user_callback`) — see [Human-in-the-Loop](../features/hitl.md).

### Step 3 — Gradually adopt patterns

Start with defaults (**auto pattern**). Routing is chosen by the built-in classifier; see [Execution Patterns](../concepts/patterns.md).

### Step 4 — Runtime bridge (optional)

If you serve a UI over **AGP**, run **`agloom-runtime serve`** and point **agloom-cli** or **agloom_web** at it — same agent instance, standardized wire events ([Protocol](../protocol/agp.md)).

---

## See also

- [The `create_agent` API](../concepts/create-agent.md)
- [Why agloom?](../getting-started/why-agloom.md)
- [LCEL as tools](lcel-as-tools.md)
- [Embedding the runtime](embedding-runtime.md)
- [Invoke input errors](../configuration/errors.md#invoke-input-errors-at-ainvoke--astream-time)
