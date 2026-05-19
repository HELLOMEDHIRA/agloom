# Quick Start

Install the Python package and a Groq chat model adapter (examples use Groq; swap in any LangChain chat model you prefer):

```bash
pip install agloom langchain-groq
export GROQ_API_KEY=gsk_...
# Optional: export GROQ_MODEL=llama-3.3-70b-versatile
```

## Your First Agent (5 Lines)

```python
import asyncio
import os

from langchain_groq import ChatGroq
from agloom import create_agent

async def main():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set GROQ_API_KEY to run this snippet.")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    llm = ChatGroq(model=model, api_key=key)
    agent = await create_agent(model=llm, name="my-first-agent")
    result = await agent.ainvoke({
        "messages": [{"role": "user", "content": "What is the capital of Japan?"}],
    })
    # Or: await agent.ainvoke("What is the capital of Japan?")
    print(result.output)

asyncio.run(main())
```

### What happened

1. `create_agent` wired up the full pipeline — classifier, pattern handlers, error handling

If you are porting from **LangChain’s** `create_agent`, see [Migrating from LangChain](../guides/migration-from-langchain.md#from-langchain-create_agent).
2. `ainvoke` classified the query and routed it to a pattern (often **DIRECT** for short factual questions — the exact pattern depends on the model and tools)
3. The handler ran and returned the result

## Inspecting the Result

`ainvoke` returns an `ExecutionResult` with rich metadata:

```python
result = await agent.ainvoke("Explain photosynthesis briefly")

print(result.output)                  # The LLM's response text
print(result.pattern_used)            # Pattern the classifier chose (e.g. DIRECT, REACT, …)
print(result.run_id)                  # Unique ID for this run
print(result.steps)                   # Step-by-step trace
print(result.token_usage)             # {'input_tokens': ..., 'output_tokens': ...}
print(result.worker_results)          # Worker outputs (for multi-agent patterns)
print(result.metadata)                # Additional metadata
```

## Adding Tools

Give your agent capabilities and it will typically route tool-heavy turns through the **REACT** pattern:

```python
import asyncio
import os
import re

from langchain_core.tools import tool
from langchain_groq import ChatGroq
from agloom import create_agent

_SAFE = re.compile(r"^[\d\s+\-*/.%()]+$")


@tool
def calculate(expression: str) -> str:
    """Evaluate a numeric expression (digits, spaces, + - * / % ** and parentheses)."""
    expr = expression.strip()
    if not expr or not _SAFE.match(expr):
        return "error: only digits, spaces, and + - * / % ** ( ) . are allowed"
    try:
        return str(eval(expr, {"__builtins__": {}}, {}))
    except Exception as exc:
        return f"error: {exc}"


async def main():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set GROQ_API_KEY to run this snippet.")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    llm = ChatGroq(model=model, api_key=key)

    agent = await create_agent(
        model=llm,
        tools=[calculate],
        name="math-agent",
    )
    result = await agent.ainvoke("What is (25 * 4) + 17?")
    print(result.pattern_used)  # often REACT when tools are used

asyncio.run(main())
```

The `calculate` helper above is intentionally tiny for docs — use a stricter evaluator in production.

## Streaming Responses

Don't make your users stare at a loading spinner.

- **`astream()`** yields **text chunks**. For a plain string query it may stream real model tokens when the run stays on the **DIRECT** fast path; other patterns usually buffer the final answer and then yield it in chunks (same iterator shape).
- **`astream_events()`** yields in-process **`AgentEvent`** objects (`thinking`, `tool_call`, `token`, `done`, …) for dashboards and custom UIs.
- **`astream_agp_events()`** yields the **typed AGP wire events** (e.g. `token.delta`, `session.opened`) — the same shapes `agloom-runtime` would serialize to NDJSON.

```python
# AGP-shaped stream (recommended when learning the wire protocol)
async for evt in agent.astream_agp_events("Tell me about Mars", thread_id="demo"):
    if evt.type == "token.delta":
        print(evt.data.text, end="", flush=True)
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

## Interactive CLI (Alternative)

The end-user CLI ships as the **Node** package **`agloom-cli`** (interactive TUI + direct mode). The `agloom` PyPI distribution exposes **`agloom-runtime`** and library APIs; it does **not** embed the Node-based shell.

```bash
npm install -g agloom-cli
# or, without a global install:
npx agloom-cli --help
```

```bash
agloom -m groq:llama-3.3-70b-versatile
agloom "Explain quantum computing in 2 sentences"
```

See the CLI overview: [GitHub source: `agloom_cli/docs/index.md`](https://github.com/HELLOMEDHIRA/agloom/blob/main/agloom_cli/docs/index.md); [Read the Docs (built copy)](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/) — same page after `make docs-prepare` / MkDocs.

## What's Next?

| Topic                     | Link                                                   |
| ------------------------- | ------------------------------------------------------ |
| Understand the 9 patterns | [Execution Patterns](../concepts/patterns.md)          |
| CLI (Node / TUI)          | [CLI on Read the Docs](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/) · [source `agloom_cli/docs/`](https://github.com/HELLOMEDHIRA/agloom/tree/main/agloom_cli/docs) |
| Every parameter explained | [All Parameters](../configuration/parameters.md)       |
| Add memory to your agent  | [Memory](../features/memory.md)                        |
| Build streaming UIs       | [Streaming & Events](../features/streaming.md)         |
| Enable LangSmith tracing  | [Observability](../features/observability.md)          |
