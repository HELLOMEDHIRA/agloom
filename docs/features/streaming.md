# Streaming & Events

## Why Streaming Matters

Without streaming, users stare at a loading spinner for 5-30 seconds, then see a wall of text. With streaming, they see the response being generated in real time — and can even watch the agent "think."

agloom provides three streaming APIs:

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

| Event | When emitted | Key data fields |
|-------|-------------|-----------------|
| `thinking` | Query classified | `output` (pattern name) |
| `token` | LLM token chunk arrives | `content` (the token text) |
| `llm_call` | LLM response completed | `name`, `output`, `duration_ms` |
| `tool_call` | Tool invoked | `id`, `name`, `input` |
| `tool_result` | Tool returned | `id`, `name`, `output` |
| `worker_start` | Worker began executing | `name` |
| `worker_end` | Worker completed | `name`, `output`, `duration_ms` |
| `cache_hit` | Cached result found | `output` |
| `reflection` | Reflection iteration ran | `output` |
| `fallback` | Pattern fallback triggered | `output` |
| `interrupt` | HITL interrupt fired | `name` |
| `done` | Execution complete | `result` (full ExecutionResult as dict) |
| `error` | Execution failed | `error` (error message) |

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

```
[classify    ] analyze_query — 450ms
[llm_call    ] supervisor_plan — 320ms
[worker_start] researcher
[worker_end  ] researcher — 890ms
[worker_start] analyst
[worker_end  ] analyst — 750ms
[llm_call    ] supervisor_synthesize — 280ms
```

### Step types

`StepType` enum values: `classify`, `llm_call`, `tool_call`, `tool_result`, `worker_start`, `worker_end`, `cache_hit`, `reflection`, `fallback`, `interrupt`, `token`.

## 4. Token Usage Tracking

Aggregated token usage across all LLM calls in a run:

```python
result = await agent.ainvoke("Explain photosynthesis")
print(result.token_usage)
# {'input_tokens': 245, 'output_tokens': 512, 'total_tokens': 757}
```

Useful for cost monitoring and billing.

## Enabling / Disabling

Streaming is always available — there's nothing to enable or disable. All three APIs (`astream`, `astream_events`, step tracing) work out of the box.

To get token usage, just access `result.token_usage` after any `ainvoke` call.

## Choosing the Right API

| Need | API | Details |
|------|-----|---------|
| Simple chat UI | `astream()` | Token chunks only, simplest integration |
| Rich "thinking" UI | `astream_events()` | Steps + tokens + tool tracking in one stream |
| Post-run analysis | `ainvoke()` + `result.steps` | Full trace with timing data |
| Server-Sent Events | `astream_events()` | Each event serializes cleanly via `event.model_dump_json()` |
