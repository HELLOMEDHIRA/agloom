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

## 2. Event Streaming — `astream_events()`

For building ChatGPT-style "thinking" UIs that show the agent's internal steps:

```python
async for event in agent.astream_events("Explain gravity"):
    if event.type == "thinking":
        show_spinner(f"Analyzing: {event.data.get('output', '')}")
    elif event.type == "tool_call":
        show_step(f"Calling: {event.data['name']}")
    elif event.type == "tool_result":
        show_step(f"Result: {event.data['output'][:50]}")
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
| `llm_call` | LLM response received | `name`, `output`, `duration_ms` |
| `tool_call` | Tool invoked | `name`, `input` |
| `tool_result` | Tool returned | `name`, `output` |
| `worker_start` | Worker began executing | `name` |
| `worker_end` | Worker completed | `name`, `output`, `duration_ms` |
| `cache_hit` | Cached result found | `output` |
| `reflection` | Reflection iteration ran | `output` |
| `fallback` | Pattern fallback triggered | `output` |
| `interrupt` | HITL interrupt fired | `name` |
| `done` | Execution complete | `result` (full ExecutionResult as dict) |

## 3. Step Tracing

Every `ExecutionResult` includes a `steps` list with a structured timeline:

```python
result = await agent.ainvoke("Complex query here")

for step in result.steps:
    print(f"[{step.type.value:12s}] {step.name} — {step.duration_ms:.0f}ms")
```

Example output:

```
[classify    ] analyze_query — 450ms
[llm_call    ] supervisor_plan — 320ms
[worker_end  ] researcher — 890ms
[worker_end  ] analyst — 750ms
[llm_call    ] supervisor_synthesize — 280ms
```

### Step types

`StepType` enum values: `classify`, `llm_call`, `tool_call`, `tool_result`, `worker_start`, `worker_end`, `cache_hit`, `reflection`, `fallback`, `interrupt`.

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
