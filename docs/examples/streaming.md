# Example: Streaming UI

Demonstrates `astream()` and `astream_events()` for building responsive UIs.

## Token Streaming

```python
import asyncio
from langchain_groq import ChatGroq
from agloom import create_agent

llm = ChatGroq(model="meta-llama/llama-4-scout-17b-16e-instruct")


async def main():
    agent = create_agent(model=llm, name="stream-agent")

    print("=== Token Streaming ===\n")
    async for token in agent.astream("Explain the Pythagorean theorem in 2 sentences"):
        print(token, end="", flush=True)
    print("\n")


asyncio.run(main())
```

## Event Streaming (ChatGPT-style "thinking" UI)

```python
async def main():
    agent = create_agent(model=llm, name="event-agent")

    print("=== Event Streaming ===\n")
    async for event in agent.astream_events("What causes rainbows?"):
        if event.type == "thinking":
            print(f"  [thinking] pattern={event.data.get('output', '')}")
        elif event.type == "llm_call":
            preview = event.data.get("output", "")[:80]
            print(f"  [llm_call] {event.data.get('name', '')} — {preview}...")
        elif event.type == "tool_call":
            print(f"  [tool]     {event.data.get('name', '')}")
        elif event.type == "done":
            result = event.data["result"]
            print(f"\n  [done] {result['output'][:120]}...")
        else:
            print(f"  [{event.type}] {event.data.get('name', '')}")


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
async def chat(query: str):
    async def event_generator():
        async for event in agent.astream_events(query):
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
```

The frontend can consume these Server-Sent Events to show thinking steps, tool calls, and the final response in real time.
