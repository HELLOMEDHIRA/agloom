# Example: Streaming UI

Demonstrates `astream()` and `astream_events()` for building responsive UIs.

## Token Streaming

```python
import asyncio
from langchain_groq import ChatGroq
from agloom import create_agent

llm = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct")


async def main():
    agent = await create_agent(model=llm, name="stream-agent")

    print("=== Token Streaming ===\n")
    async for token in agent.astream("Explain the Pythagorean theorem in 2 sentences"):
        print(token, end="", flush=True)
    print("\n")


asyncio.run(main())
```

## Event Streaming (ChatGPT-style "thinking" UI)

`astream_events()` provides **both** structured step events **and** real-time token chunks in a single stream:

```python
async def main():
    agent = await create_agent(model=llm, name="event-agent")

    print("=== Event Streaming ===\n")
    async for event in agent.astream_events("What causes rainbows?"):
        if event.type == "thinking":
            print(f"  [thinking] pattern={event.data.get('output', '')}")
        elif event.type == "token":
            # Real-time token streaming — fires DURING each LLM call
            print(event.data["content"], end="", flush=True)
        elif event.type == "llm_call":
            preview = event.data.get("output", "")[:80]
            print(f"\n  [llm_call] {event.data.get('name', '')} — {preview}...")
        elif event.type == "tool_call":
            tc_id = event.data.get("id", "")
            print(f"\n  [tool_call] {event.data.get('name', '')} [{tc_id}]")
        elif event.type == "tool_result":
            tc_id = event.data.get("id", "")
            print(f"  [tool_result] {event.data.get('name', '')} [{tc_id}]: "
                  f"{event.data.get('output', '')[:50]}")
        elif event.type == "done":
            result = event.data["result"]
            print(f"\n\n  [done] {result['output'][:120]}...")
        else:
            print(f"\n  [{event.type}] {event.data.get('name', '')}")


asyncio.run(main())
```

## Session-Aware Streaming

Pass `thread_id` and `user_id` to maintain conversation context:

```python
async def main():
    agent = await create_agent(model=llm, name="chat-agent")

    # First turn — establish context
    async for event in agent.astream_events(
        "My name is Alice and I like Python",
        thread_id="session-1",
        user_id="user-42",
    ):
        if event.type == "token":
            print(event.data["content"], end="", flush=True)
        elif event.type == "done":
            print()

    # Second turn — agent remembers
    async for event in agent.astream_events(
        "What's my name and favorite language?",
        thread_id="session-1",
        user_id="user-42",
    ):
        if event.type == "token":
            print(event.data["content"], end="", flush=True)
        elif event.type == "done":
            print()


asyncio.run(main())
```

## Tool Call Tracking

Track parallel tool calls with correlated `id` fields:

```python
from langchain_core.tools import tool


@tool
def search(query: str) -> str:
    """Search the web."""
    return f"Results for: {query}"


@tool
def calculate(expression: str) -> str:
    """Evaluate math."""
    return str(eval(expression))


async def main():
    agent = await create_agent(model=llm, tools=[search, calculate], name="tool-agent")
    pending = {}

    async for event in agent.astream_events("Search for Pi and calculate Pi*2"):
        if event.type == "token":
            print(event.data["content"], end="", flush=True)
        elif event.type == "tool_call":
            tc_id = event.data["id"]
            pending[tc_id] = event.data["name"]
            print(f"\n⏳ Calling {event.data['name']}...")
        elif event.type == "tool_result":
            tc_id = event.data["id"]
            name = pending.pop(tc_id, "unknown")
            print(f"✅ {name}: {event.data['output'][:50]}")
        elif event.type == "done":
            print(f"\n\nFinal: {event.data['result']['output'][:100]}")


asyncio.run(main())
```

## Run it

```bash
python examples/03_streaming.py
```

## Building a Web UI

Here's how you'd use `astream_events` in a FastAPI endpoint:

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.post("/chat")
async def chat(query: str, thread_id: str = None, user_id: str = None):
    async def event_generator():
        async for event in agent.astream_events(
            query,
            thread_id=thread_id,
            user_id=user_id,
        ):
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
```

The frontend can consume these Server-Sent Events to show thinking steps, tool calls, streaming tokens, and the final response — all in real time.
