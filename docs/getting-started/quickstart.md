# Quick Start

## Your First Agent (5 Lines)

```python
import asyncio
from langchain_groq import ChatGroq
from agloom import create_agent

async def main():
    llm = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct")
    agent = create_agent(model=llm, name="my-first-agent")
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
from langchain_core.tools import tool

@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression."""
    return str(eval(expression))

agent = create_agent(
    model=llm,
    tools=[calculate],
    name="math-agent",
)

result = await agent.ainvoke("What is (25 * 4) + 17?")
print(result.pattern_used)  # → PatternType.REACT
```

## Streaming Responses

Don't make your users stare at a loading spinner:

```python
# Token-by-token streaming
async for token in agent.astream("Tell me about Mars"):
    print(token, end="", flush=True)
```

## Graceful Cleanup

Use the context manager to ensure resources (MCP connections, feedback handlers) are cleaned up:

```python
async with create_agent(model=llm, name="safe-agent") as agent:
    result = await agent.ainvoke("Hello!")
# Everything cleaned up here
```

## What's Next?

| Topic | Link |
|-------|------|
| Understand the 9 patterns | [Execution Patterns](../concepts/patterns.md) |
| Every parameter explained | [All Parameters](../configuration/parameters.md) |
| Add memory to your agent | [Memory](../features/memory.md) |
| Build streaming UIs | [Streaming & Events](../features/streaming.md) |
| Enable LangSmith tracing | [Observability](../features/observability.md) |
