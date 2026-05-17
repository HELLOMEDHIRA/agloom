# Streaming & Events

## Why Streaming Matters

Without streaming, users stare at a loading spinner for 5-30 seconds, then see a wall of text. With streaming, they see the response being generated in real time — and can even watch the agent "think."

agloom provides complementary streaming APIs (tokens, rich agent events, and optional AGP envelopes):

## 1. Token Streaming — `astream()`

Stream response tokens as they arrive from the LLM:

```python
async for token in agent.astream("Explain quantum computing"):
    print(token, end="", flush=True)
```

### How it works

- For **DIRECT** pattern: true token-by-token streaming from the LLM's `astream()` method
- For complex patterns (REACT, SUPERVISOR, etc.): the full pipeline runs, then the final output is streamed word-by-word

### Stream modes

```python
# Token mode (default) — yields str chunks
async for token in agent.astream("Hello", stream_mode="tokens"):
    print(token, end="")

# Result mode — yields a single ExecutionResult at the end
async for result in agent.astream("Hello", stream_mode="result"):
    print(result.output)
    print(result.pattern_used)
```

### Runtime parameters

All streaming methods accept `thread_id`, `user_id`, and `context`:

```python
async for token in agent.astream(
    "Hello",
    thread_id="session-1",    # session memory
    user_id="user-42",        # cross-session identity
    context={"source": "web"},
    stream_mode="tokens",
):
    print(token, end="")
```

## 2. Event Streaming — `astream_events()`

For building ChatGPT-style "thinking" UIs that show the agent's internal steps **and** stream tokens in real-time.

### AGP-shaped events — `astream_agp_events()`

If you are building a **custom CLI, web UI, or test harness** that should consume the same **Agloom Protocol (AGP)** event model as `agloom-runtime` (typed envelopes, not ad-hoc `AgentEvent` dicts), use `UnifiedAgent.astream_agp_events()`. It runs the same pipeline as `astream_events()`, but each item is a Pydantic :class:`~agloom.protocol.Envelope` subclass (`TokenDelta`, `PatternClassified`, `ToolCallStart`, …) produced via :func:`agloom.runtime.translator.translate`.

The stream is bracketed by **`session.opened`** at the start and **`session.closed`** at the end, so you can treat one call as a self-contained AGP session without constructing a :class:`~agloom.protocol.SessionEmitter` yourself.

```python
async for evt in agent.astream_agp_events(
    "Read pyproject.toml",
    thread_id="t_demo",
    session_id="s_demo",
):
    if evt.type == "token.delta":
        print(evt.data.text, end="", flush=True)
    elif evt.type == "worker.spawned":
        print(f"[worker] {evt.data.worker_id}: {evt.data.task}")
    elif evt.type == "metric.tokens":
        print(f"tokens: {evt.data.input_tokens}↑ {evt.data.output_tokens}↓")
```

Wire-format details, command vocabulary, and schema export live in [**AGP — Agloom Protocol**](../protocol/agp.md). For how **`metric.tokens`** is produced without double-counting, see [Wire tokens & metric.tokens](wire-tokens.md). For embedding the runtime bridge and stores in Python, see [AGP from Python](../guides/agp-python.md) and [Embedding the runtime](../guides/embedding-runtime.md).

Everything below applies to **`astream_events()`**, which yields **`AgentEvent`** instances (`event.type` string + `event.data` dict) until the run completes.

!!! tip "Combined token + event streaming"
    `astream_events()` provides **both** structured step events **and** real-time token chunks in a single stream. This matches the industry standard set by LangGraph's `astream_events(version="v2")`.

### Real-time token streaming for ALL patterns

Token events fire **during** each LLM call as chunks arrive — not after the call completes. This works for **all** patterns including REACT and SUPERVISOR:

```python
async for event in agent.astream_events("Explain gravity"):
    if event.type == "thinking":
        show_spinner(f"Analyzing: {event.data.get('output', '')}")
    elif event.type == "token":
        # Real-time token — fires DURING each LLM call
        print(event.data["content"], end="", flush=True)
    elif event.type == "tool_call":
        tc_id = event.data.get("id", "")
        show_step(f"Calling: {event.data['name']} [{tc_id}]")
    elif event.type == "tool_result":
        tc_id = event.data.get("id", "")
        show_step(f"Result [{tc_id}]: {event.data['output'][:50]}")
    elif event.type == "worker_start":
        show_step(f"Worker started: {event.data['name']}")
    elif event.type == "worker_end":
        show_step(f"Worker done: {event.data['name']}")
    elif event.type == "llm_call":
        show_step(f"LLM: {event.data.get('output', '')[:80]}")
    elif event.type == "done":
        result = event.data["result"]
        show_final(result["output"])
```

### Event types

| Event          | When emitted               | Key data fields                         |
| -------------- | -------------------------- | --------------------------------------- |
| `thinking`     | Query classified           | `output` (pattern name)                 |
| `token`        | LLM token chunk arrives    | `content` (the token text)              |
| `llm_call`     | LLM response completed     | `name`, `output`, `duration_ms`         |
| `tool_call`    | Tool invoked               | `id`, `name`, `input`                   |
| `tool_result`  | Tool returned              | `id`, `name`, `output`                  |
| `worker_start` | Worker began executing     | `name`                                  |
| `worker_end`   | Worker completed           | `name`, `output`, `duration_ms`         |
| `cache_hit`    | Cached result found        | `output`                                |
| `reflection`   | Reflection iteration ran   | `output`                                |
| `fallback`     | Pattern fallback triggered | `output`                                |
| `interrupt`    | HITL interrupt fired       | `name`                                  |
| `done`         | Execution complete         | `result` (full ExecutionResult as dict) |
| `error`        | Execution failed           | `error` (error message)                 |

### Tool call correlation with `id`

Every `tool_call` and `tool_result` event includes an `id` field that links them together. This is essential for:

- UI spinners that show "calling tool X..." and dismiss on the matching result
- Parallel tool execution tracking
- Debugging and tracing

```python
pending_tools = {}

async for event in agent.astream_events("Search and calculate"):
    if event.type == "tool_call":
        tc_id = event.data["id"]
        pending_tools[tc_id] = event.data["name"]
        print(f"⏳ Calling {event.data['name']}...")

    elif event.type == "tool_result":
        tc_id = event.data["id"]
        tool_name = pending_tools.pop(tc_id, "unknown")
        print(f"✅ {tool_name} returned: {event.data['output'][:50]}")
```

### Events are live, not replayed

Events are pushed to the consumer **as they happen** during execution — not collected and replayed after completion. This means:

- `thinking` events appear immediately when classification finishes
- `token` events stream during each LLM call (not after)
- `tool_call` events fire when tools are invoked
- `worker_start`/`worker_end` events bracket worker execution
- `done` fires only when the full pipeline completes

### SUPERVISOR tool events

For the SUPERVISOR pattern, tool events from each worker are emitted **post-hoc** — when a worker completes, its `tool_call` and `tool_result` events are emitted in sequence before `worker_end`. Each tool event includes a `worker_id` field so UI consumers can group them:

```python
async for event in agent.astream_events("Research and analyze"):
    if event.type == "worker_start":
        print(f"▶ {event.data['name']} started")
    elif event.type == "tool_call":
        worker = event.data.get("worker_id", "")
        print(f"  🔧 [{worker}] calling {event.data['name']}")
    elif event.type == "tool_result":
        worker = event.data.get("worker_id", "")
        print(f"  ✅ [{worker}] {event.data['name']}: {event.data['output'][:50]}")
    elif event.type == "worker_end":
        print(f"◼ {event.data['name']} done ({event.data['duration_ms']:.0f}ms)")
```

!!! note "Post-hoc vs real-time"
    SUPERVISOR tool events are emitted when each worker finishes, not in real-time during worker execution. This keeps the event stream ordered and avoids interleaving from parallel workers. REACT tool events are emitted in real-time as tools execute.

## 3. Step Tracing

Every `ExecutionResult` includes a `steps` list with a structured timeline:

```python
result = await agent.ainvoke("Complex query here")

for step in result.steps:
    print(f"[{step.type.value:12s}] {step.name} — {step.duration_ms:.0f}ms")
    # Tool call/result steps include an id for correlation:
    if step.type.value in ("tool_call", "tool_result"):
        print(f"              tool_call_id={step.metadata.get('id', 'N/A')}")
```

Example output:

```text
[classify    ] analyze_query — 450ms
[llm_call    ] supervisor_plan — 320ms
[worker_start] researcher
[tool_call   ] search_api            (worker: researcher)
[tool_result ] search_api            (worker: researcher)
[worker_end  ] researcher — 890ms
[worker_start] analyst
[tool_call   ] calculator            (worker: analyst)
[tool_result ] calculator            (worker: analyst)
[worker_end  ] analyst — 750ms
[llm_call    ] supervisor_synthesize — 280ms
```

### Step types

`StepType` enum values: `classify`, `llm_call`, `tool_call`, `tool_result`, `worker_start`, `worker_end`, `cache_hit`, `reflection`, `fallback`, `interrupt`, `token`.

### Controlling step output length

By default, step `input` and `output` fields are **not truncated** — you get the full tool response. If you need to limit memory usage (e.g., high-throughput batch processing), set `max_step_output_length` to a positive value:

Default — full tool output in steps:

```python
async def main():
    agent = await create_agent(model=llm, tools=[search_products])

    result = await agent.ainvoke("Find running shoes")
    for step in result.steps:
        if step.type == StepType.TOOL_RESULT:
            # step.output contains the FULL tool response
            products = json.loads(step.output)
            render_carousel(products)
```

Opt-in truncation for memory-sensitive deployments:

```python
async def main():
    agent = await create_agent(
        model=llm,
        tools=[search_products],
        max_step_output_length=500,  # truncate step data to 500 chars
    )
```

## 4. Token Usage Tracking

Aggregated token usage across all LLM calls in a run:

```python
result = await agent.ainvoke("Explain photosynthesis")
print(result.token_usage)
# {'input_tokens': 245, 'output_tokens': 512, 'total_tokens': 757}
```

Useful for cost monitoring and billing. On the AGP wire, **`metric.cost`** uses provider metadata when present; otherwise the runtime emits an approximate estimate (`estimated: true` on the event — not invoice-grade).

## 5. Raw LangChain Messages

Every `ExecutionResult` includes a `messages` field containing the raw LangChain message objects from the execution:

```python
result = await agent.ainvoke("What is 3 + 5?")

for msg in result.messages:
    print(f"{type(msg).__name__}: {msg.content[:80]}")
# HumanMessage: What is 3 + 5?
# AIMessage: (tool_calls=[...])
# ToolMessage: 8
# AIMessage: The result of 3 + 5 is 8.
```

This gives you direct access to:

- **`AIMessage.tool_calls`** — structured tool call data (name, args, id)
- **`ToolMessage.content`** — raw tool output
- **`AIMessage.content`** — full LLM response text
- **`AIMessage.usage_metadata`** — per-message token counts

Useful for UI libraries (e.g. `@assistant-ui/react`) that render message objects directly, or for building custom tool visualization:

```python
from langchain_core.messages import AIMessage, ToolMessage

for msg in result.messages:
    if isinstance(msg, AIMessage) and msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"Called {tc['name']}({tc['args']})")
    elif isinstance(msg, ToolMessage):
        print(f"Tool {msg.name} returned: {msg.content}")
```

Worker results also carry their own messages:

```python
for wr in result.worker_results:
    print(f"Worker {wr.worker_id}: {len(wr.messages)} messages")
```

## Enabling / Disabling

Streaming is always available — there's nothing to enable or disable. `astream`, `astream_events`, `astream_agp_events`, and post-hoc step tracing on `ExecutionResult` all work out of the box.

To get token usage, just access `result.token_usage` after any `ainvoke` call.

## Choosing the Right API

| Need                         | API                                          | Details                                                                    |
| ---------------------------- | -------------------------------------------- | -------------------------------------------------------------------------- |
| Simple chat UI               | `astream()`                                  | Token chunks only, simplest integration                                    |
| Rich "thinking" UI           | `astream_events()`                           | Steps + tokens + tool tracking in one stream (`AgentEvent`)                |
| Same shapes as AGP / runtime | `astream_agp_events()`                       | Typed `Envelope` subclasses; bracketed `session.opened` / `session.closed` |
| Post-run analysis            | `ainvoke()` + `result.steps`                 | Full trace with timing data                                                |
| Raw message access           | `ainvoke()` + `result.messages`              | Full LangChain message objects                                             |
| NDJSON / SSE bridges         | `astream_agp_events()` or `astream_events()` | AGP events serialize to JSON lines; agent events via `model_dump_json()`   |
