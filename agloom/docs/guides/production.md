# Production integration

Ship agloom agents behind APIs, workers, and multi-tenant products. This guide covers streaming, persistence, structured output, scaling knobs, and operational hygiene — without requiring you to wire orchestration by hand.

## Production checklist

| Concern | What to configure |
| -------- | ----------------- |
| **Secrets** | Provider API keys via env / secret store — never bake into images |
| **Persistence** | `checkpointer` + durable `store` for threads; SQLite or your own `BaseStore` backend |
| **Timeouts** | `llm_timeout`, `classifier_timeout` — see [Timeouts & retries](../configuration/reliability.md) |
| **Concurrency** | `max_concurrent`, optional `rate_limit` for provider quotas |
| **HITL** | `interrupt_before` / `user_callback` for destructive tools — see [Human-in-the-loop](../features/hitl.md) |
| **Observability** | LangSmith env vars, `debug=True` in staging, `agloom-runtime serve --obs` for dashboards |
| **Wire UI** | `astream_events` or AGP via `agloom-runtime` — see [Streaming](../features/streaming.md) |

---

## FastAPI with Server-Sent Events (SSE)

A common pattern: REST endpoint that streams agent events to the browser.

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

For the **AGP wire** (CLI, web workspace, custom clients), run [`agloom-runtime serve`](../runtime/cli.md) and consume NDJSON/WebSocket events — same semantics, standardized envelope. See [Deployment](deployment.md).

---

## Persistent storage

By default, in-process stores lose data on restart. For production:

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

### Session memory

```python
from agloom import SessionMemory

async def main():
    agent = await create_agent(
        model=llm,
        memory=SessionMemory(store=your_persistent_store, max_turns=50),
        name="persistent-chat",
    )
```

!!! info "Long-term memory vs process lifetime"
    Skills, feedback, and long-term memory need a durable **`store=`** across restarts. Session turns are keyed by **`thread_id`**; tenant isolation uses **`user_id`** and **`lt_namespace`**.

---

## Structured output

Force responses into a Pydantic schema with **`response_format`**:

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
    print(result.output)  # JSON matching AnalysisResult
```

After the main pipeline completes, agloom runs a **formatting pass** (extra LLM call with structured output). If formatting fails after **`structured_max_retries`**, the raw assistant text is returned and a warning is logged. Tune retries in [Timeouts & retries](../configuration/reliability.md).

---

## Dynamic system prompts

Pass a callable as **`system_prompt`** to adapt instructions per user or query:

```python
async def dynamic_prompt(state: dict) -> str:
    user_id = state.get("user_id")
    query = state.get("query", "")

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

Callable **`state`** keys:

| Key | Description |
| --- | ----------- |
| `query` | Raw user message |
| `thread_id` | Conversation thread |
| `user_id` | Caller id when passed to `ainvoke` / `astream_events` |
| `context` | Dict from `ainvoke(context=...)` |
| `messages` | Reserved (empty today) |

---

## Multi-worker patterns (supervisor / pipeline)

### Per-worker token usage

```python
result = await agent.ainvoke("Compare solar, wind, and hydro energy")

if result.worker_results:
    for wr in result.worker_results:
        print(f"Worker '{wr.worker_id}': {wr.token_usage}")
    print(f"Total: {result.token_usage}")
```

### Partial failure

In supervisor-style runs, some workers can fail while synthesis still completes:

```python
result = await agent.ainvoke("Research 3 complex topics")

for wr in result.worker_results:
    if wr.signal and wr.signal.signal_type.value == "FAILED":
        print(f"Worker '{wr.worker_id}' failed")
```

!!! warning "success does not mean every worker succeeded"
    **`result.success`** means the top-level run finished (including synthesis). Inspect **`worker_results`** when you need per-subtask guarantees.

Workers share the same **`model`** passed to **`create_agent`** — per-worker model overrides are not supported today.

---

## Checkpointer: state and resume

```python
from langgraph.checkpoint.memory import MemorySaver

async def main():
    agent = await create_agent(
        model=llm,
        checkpointer=MemorySaver(),
        name="persistent-agent",
    )

    result = await agent.ainvoke("Explain RLHF", thread_id="session-1")
```

### Inspecting state

```python
state = await agent.get_state(thread_id="session-1")
if state:
    data = state.checkpoint["channel_values"]
    print(f"Query: {data['query']}")
    print(f"Pattern: {data['pattern']}")
    print(f"Output: {data['output']}")
```

Checkpoints store the classifier decision (**`analysis`**) so **`resume()`** after HITL does not re-route to a different pattern mid-interrupt.

### History

```python
async for snapshot in await agent.get_history(thread_id="session-1"):
    data = snapshot.checkpoint["channel_values"]
    print(f"{data['query']} → {data['pattern']}")
```

### Graph interrupt resume

```python
result = await agent.resume(
    value="user approved",
    thread_id="session-1",
)
```

Use **`resume()`** only with **`interrupt_before` / `interrupt_after`** and a checkpointer — not for ordinary chat turns.

---

## Multi-tenancy

Isolate tenants with **`thread_id`**, **`user_id`**, and **`lt_namespace`**:

```python
@app.post("/chat/{tenant_id}")
async def chat(tenant_id: str, query: str, user_id: str):
    result = await agent.ainvoke(
        query,
        thread_id=f"{tenant_id}:{user_id}:session",
        user_id=user_id,
        lt_namespace=(tenant_id, user_id),
        context={"tenant_id": tenant_id},
    )
    return {"output": result.output}
```

| Data | Isolation key |
| ---- | ------------- |
| Session memory | `thread_id` |
| Long-term memory | `lt_namespace` or `user_id` |
| Skills / feedback | Agent `name` + `store` |
| Query cache | Shared process-wide (plan tenant boundaries accordingly) |

---

## Testing agents

### Deterministic mock LLM

```python
from langchain_core.language_models.fake import FakeListChatModel

mock_llm = FakeListChatModel(responses=["The answer is 42."])

async def main():
    agent = await create_agent(model=mock_llm, name="test-agent")
    result = await agent.ainvoke("What is the answer?")
    assert "42" in result.output
```

### Step traces

```python
async def test_steps(agent):
    result = await agent.ainvoke("Calculate 2+2")
    step_types = [s.type.value for s in result.steps]
    assert "classify" in step_types
    assert result.pattern_used.value in ("DIRECT", "REACT")
```

---

## Docker deployment

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Health and shutdown

```python
@app.get("/health")
async def health():
    return {"status": "ok", "agent": agent.name if agent else "not initialized"}
```

Use FastAPI **`lifespan`** (above) so MCP connections and feedback handlers close cleanly on SIGTERM.

For **runtime + web** stacks, see [Production deployment](deployment.md).

---

## See also

- [Timeouts & retries](../configuration/reliability.md)
- [Parameters](../configuration/parameters.md)
- [Patterns](../concepts/patterns.md) — what the classifier picks
- [Embedding the runtime](embedding-runtime.md) — custom AGP servers
