# Quick Start

## Your First Agent (5 Lines)

```python
import asyncio
from langchain_groq import ChatGroq
from agloom import create_agent

async def main():
    llm = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct")
    agent = await create_agent(model=llm, name="my-first-agent")
    result = await agent.ainvoke("What is the capital of Japan?")
    print(result.output)

asyncio.run(main())
```

**What happened?**

1. `create_agent` wired up the full pipeline — classifier, pattern handlers, error handling
2. `ainvoke` classified the query → selected **DIRECT** pattern (simple factual query)
3. Made one LLM call and returned the result

## Inspecting the Result

`ainvoke` returns an `ExecutionResult` with rich metadata:

```python
result = await agent.ainvoke("Explain photosynthesis briefly")

print(result.output)                  # The LLM's response text
print(result.pattern_used)            # PatternType.DIRECT
print(result.run_id)                  # Unique ID for this run
print(result.steps)                   # Step-by-step trace
print(result.token_usage)             # {'input_tokens': ..., 'output_tokens': ...}
print(result.worker_results)          # Worker outputs (for multi-agent patterns)
print(result.metadata)                # Additional metadata
```

## Adding Tools

Give your agent capabilities and it will automatically switch to the **REACT** pattern:

```python
import asyncio
from langchain_core.tools import tool
from agloom import create_agent

@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression."""
    return str(eval(expression))

async def main():
    agent = await create_agent(
        model=llm,
        tools=[calculate],
        name="math-agent",
    )
    result = await agent.ainvoke("What is (25 * 4) + 17?")
    print(result.pattern_used)  # → PatternType.REACT

asyncio.run(main())
```

## Streaming Responses

Don't make your users stare at a loading spinner:

```python
# Token-by-token streaming
async for token in agent.astream("Tell me about Mars"):
    print(token, end="", flush=True)
```

## Conversation Memory

Session memory is **always active** (auto-created with an ephemeral store). To use it across calls, pass the **same `thread_id`**:

```python
# Without thread_id — each call is isolated (random UUID)
await agent.ainvoke("My name is Alice")
await agent.ainvoke("What's my name?")  # won't remember!

# With thread_id — conversation memory works
result = await agent.ainvoke("My name is Alice", thread_id="session-1")
result = await agent.ainvoke("What's my name?", thread_id="session-1")
# → "Your name is Alice"
```

For **cross-session** identity (long-term memory), pass `user_id` at call time along with a `store`:

```python
import asyncio
from langgraph.store.memory import InMemoryStore
from agloom import create_agent

async def main():
    agent = await create_agent(model=llm, store=InMemoryStore(), name="my-agent")
    # user_id must be passed at call time to activate user-scoped memory
    result = await agent.ainvoke(
        "Save my preference: dark mode",
        thread_id="s1",
        user_id="user-42",
    )

asyncio.run(main())
```

All runtime methods (`ainvoke`, `astream`, `astream_events`, `abatch`) accept `thread_id`, `user_id`, and `context`. See [Memory](../features/memory.md) for details.

## Graceful Cleanup

Use the context manager to ensure resources (MCP connections, feedback handlers) are cleaned up:

```python
async with await create_agent(model=llm, name="safe-agent") as agent:
    result = await agent.ainvoke("Hello!")
# Everything cleaned up here
```

## CLI Shell (Alternative)

Prefer CLI over Python? Use the built-in shell:

```bash
pip install agloom
agloom  # Start interactive shell
```

```bash
agloom "Explain quantum computing in 2 sentences"
agloom -m llama-3.3-70b-versatile  # Use Groq model
```

See [CLI Shell](cli.md) for full reference.

## What's Next?

| Topic | Link |
|-------|------|
| Understand the 9 patterns | [Execution Patterns](../concepts/patterns.md) |
| CLI Shell | [CLI Shell](cli.md) |
| Every parameter explained | [All Parameters](../configuration/parameters.md) |
| Add memory to your agent | [Memory](../features/memory.md) |
| Build streaming UIs | [Streaming & Events](../features/streaming.md) |
| Enable LangSmith tracing | [Observability](../features/observability.md) |
