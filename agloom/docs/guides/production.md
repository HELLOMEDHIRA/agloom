# Production Integration Guide

How to deploy agloom agents in production applications.

## FastAPI with Server-Sent Events (SSE)

The most common production pattern — a REST API that streams agent events to the frontend:

```python
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from langchain_groq import ChatGroq
from agloom import create_agent

agent = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    llm = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct")
    agent = await create_agent(model=llm, name="api-agent")
    yield
    await agent.aclose()

app = FastAPI(lifespan=lifespan)


@app.post("/chat")
async def chat(query: str, thread_id: str | None = None, user_id: str | None = None):
    async def event_stream():
        async for event in agent.astream_events(
            query,
            thread_id=thread_id,
            user_id=user_id,
        ):
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@app.post("/invoke")
async def invoke(query: str, thread_id: str | None = None, user_id: str | None = None):
    result = await agent.ainvoke(query, thread_id=thread_id, user_id=user_id)
    return {
        "output": result.output,
        "pattern": result.pattern_used.value,
        "steps": len(result.steps),
        "tokens": result.token_usage,
        "run_id": result.run_id,
    }
```

### Frontend (JavaScript)

```javascript
const eventSource = new EventSource("/chat?query=Hello&thread_id=s1");

eventSource.onmessage = (e) => {
    const event = JSON.parse(e.data);

    if (event.type === "token") {
        appendToChat(event.data.content);
    } else if (event.type === "tool_call") {
        showToolSpinner(event.data.name, event.data.id);
    } else if (event.type === "tool_result") {
        hideToolSpinner(event.data.id);
    } else if (event.type === "done") {
        eventSource.close();
    } else if (event.type === "error") {
        showError(event.data.error);
        eventSource.close();
    }
};
```

## Persistent Storage

By default, agloom uses `InMemoryStore` which loses all data on restart. For production, use a persistent store:

### SQLite (single server)

```python
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async def main():
    agent = await create_agent(
        model=llm,
        store=InMemoryStore(),
        checkpointer=AsyncSqliteSaver.from_conn_string("agent.db"),
        name="persistent-agent",
    )
```

### Session memory persistence

```python
from agloom import SessionMemory

async def main():
    agent = await create_agent(
        model=llm,
        memory=SessionMemory(store=your_persistent_store, max_turns=50),
        name="persistent-chat",
    )
```

!!! info "InMemoryStore for long-term features"
    `InMemoryStore` still works for skills, feedback, and long-term memory during the process lifetime. For true persistence across restarts, implement a `BaseStore`-compatible backend or use LangGraph's persistence options.

## Structured Output

Force the agent to return data in a specific schema using `response_format`:

```python
from pydantic import BaseModel

class AnalysisResult(BaseModel):
    summary: str
    sentiment: str  # "positive" | "negative" | "neutral"
    confidence: float
    key_points: list[str]

async def main():
    agent = await create_agent(
        model=llm,
        response_format=AnalysisResult,
        name="analyzer",
    )

    result = await agent.ainvoke("Analyze this customer review: Great product, fast shipping!")
    print(result.output)  # JSON string matching AnalysisResult schema
```

!!! info "How it works"
    `response_format` adds a **post-processing step** after the main pipeline. The raw output is reformatted into the Pydantic model via an additional LLM call using `with_structured_output`. If formatting fails after `structured_max_retries` attempts, the raw output is returned with a warning logged.

## Dynamic System Prompts

Pass a callable as `system_prompt` to generate prompts based on runtime context:

```python
async def dynamic_prompt(state: dict) -> str:
    user_id = state.get("user_id")
    query = state.get("query", "")
    thread_id = state.get("thread_id", "")

    base = "You are a helpful assistant."
    if user_id:
        prefs = await load_user_preferences(user_id)
        base += f"\nUser preferences: {prefs}"
    if "code" in query.lower():
        base += "\nFormat code responses with syntax highlighting."
    return base

async def main():
    agent = await create_agent(
        model=llm,
        system_prompt=dynamic_prompt,
        name="adaptive-agent",
    )
```

The callable receives a state dict with these keys:

| Key         | Type   | Description                              |                                  |
| ----------- | ------ | ---------------------------------------- | -------------------------------- |
| `query`     | `str`  | The raw user query                       |                                  |
| `thread_id` | `str`  | Current thread ID                        |                                  |
| `user_id`   | `str \ | None`                                    | User ID (if passed at call time) |
| `context`   | `dict` | Context dict from `ainvoke(context=...)` |                                  |
| `messages`  | `list` | Always `[]` (reserved for future use)    |                                  |

## Worker Details (SUPERVISOR / PIPELINE)

### Per-worker token usage

Each worker's token usage is available in `result.worker_results`:

```python
result = await agent.ainvoke("Compare solar, wind, and hydro energy")

if result.worker_results:
    for wr in result.worker_results:
        print(f"Worker '{wr.worker_id}': {wr.token_usage}")
    print(f"Total: {result.token_usage}")
```

### Partial failure handling

In SUPERVISOR pattern, some workers can fail while others succeed. The synthesis step still runs with available results:

```python
result = await agent.ainvoke("Research 3 complex topics")
print(f"Success: {result.success}")  # True even with partial failures

for wr in result.worker_results:
    if wr.signal and wr.signal.signal_type.value == "FAILED":
        print(f"Worker '{wr.worker_id}' failed")
    else:
        print(f"Worker '{wr.worker_id}' succeeded")
```

!!! warning "Check worker_results"
    `result.success = True` means the synthesis completed, not that all workers succeeded. Always inspect `result.worker_results` when reliability matters.

### All workers share the agent's LLM

Workers use the same `model` passed to `create_agent`. Per-worker model customization is not currently supported — all workers run against the same LLM.

## Checkpointer: State Persistence and Inspection

Pass a `checkpointer` to automatically persist execution state after every `ainvoke()` and `astream_events()` call:

```python
from langgraph.checkpoint.memory import MemorySaver

async def main():
    agent = await create_agent(
        model=llm,
        checkpointer=MemorySaver(),
        name="persistent-agent",
    )

    # Every call writes a checkpoint keyed by thread_id
    result = await agent.ainvoke("Explain RLHF", thread_id="session-1")
```

### Inspecting state

```python
state = await agent.get_state(thread_id="session-1")
if state:
    checkpoint = state.checkpoint
    data = checkpoint["channel_values"]
    print(f"Query: {data['query']}")
    print(f"Pattern: {data['pattern']}")
    print(f"Output: {data['output'][:100]}")
    print(f"Steps: {len(data['steps'])}")
```

### State history (time travel)

Multiple calls to the same `thread_id` create a history of checkpoints:

```python
async for snapshot in await agent.get_history(thread_id="session-1"):
    data = snapshot.checkpoint["channel_values"]
    print(f"[{snapshot.checkpoint['ts']}] {data['query'][:60]} → {data['pattern']}")
```

### Resuming interrupted runs

`resume()` operates on the **compiled LangGraph graph** path (not the normal `run_fresh` pipeline). It is intended for advanced interrupt/resume workflows where `interrupt_before` gates paused a graph node:

```python
result = await agent.resume(
    value="user approved",
    thread_id="session-1",
)
```

!!! note "Checkpoint vs resume"
    `get_state()` and `get_history()` read checkpoints written by every `ainvoke()`/`astream_events()` call — they always have data. `resume()` requires the compiled graph path and is for advanced HITL workflows only.

## Testing Agents

### Mock LLM for deterministic tests

```python
from langchain_core.language_models.fake import FakeListChatModel

mock_llm = FakeListChatModel(
    responses=["The answer is 42."]
)

async def main():
    agent = await create_agent(model=mock_llm, name="test-agent")
    result = await agent.ainvoke("What is the answer?")
    assert "42" in result.output
```

### Testing with tools

```python
from langchain_core.tools import tool

@tool
def search(query: str) -> str:
    """Search the web."""
    return "Mock search result for: " + query

async def main():
    agent = await create_agent(model=mock_llm, tools=[search], name="test-tool-agent")
```

### Asserting step traces

```python
async def test_steps(agent):
    result = await agent.ainvoke("Calculate 2+2")

    step_types = [s.type.value for s in result.steps]
    assert "classify" in step_types
    assert result.pattern_used.value in ("DIRECT", "REACT")
```

## Docker Deployment

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Health check

```python
@app.get("/health")
async def health():
    return {"status": "ok", "agent": agent.name if agent else "not initialized"}
```

### Graceful shutdown

The `lifespan` context manager pattern (shown in the FastAPI section above) ensures MCP connections and feedback handlers are properly closed on shutdown.

## Multi-Tenancy

Isolate data between tenants using `user_id` and `lt_namespace`:

```python
@app.post("/chat/{tenant_id}")
async def chat(tenant_id: str, query: str, user_id: str):
    result = await agent.ainvoke(
        query,
        thread_id=f"{tenant_id}:{user_id}:session",
        user_id=user_id,
        lt_namespace=(tenant_id, user_id),  # explicit tenant isolation
        context={"tenant_id": tenant_id},
    )
    return {"output": result.output}
```

Key isolation points:

| Data             | Isolated by                            |
| ---------------- | -------------------------------------- |
| Session memory   | `thread_id`                            |
| Long-term memory | `lt_namespace` or `user_id`            |
| Skills           | Agent `name` + `store`                 |
| Feedback         | Agent `name` + `store`                 |
| Query cache      | Not isolated (shared across all users) |
