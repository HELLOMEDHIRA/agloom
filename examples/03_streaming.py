"""Streaming — demonstrates astream() and astream_events() for UI integration."""

import asyncio
import os

from langchain_groq import ChatGroq

from agloom import create_agent

llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.environ["GROQ_API_KEY"],
    temperature=0,
)


async def demo_token_stream():
    """Token-level streaming — prints tokens as they arrive."""
    print("=== Token Streaming ===\n")
    agent = await create_agent(model=llm, name="stream-agent")

    async for token in agent.astream(
        "Explain the Pythagorean theorem in 2 sentences",
        thread_id="demo-session",
    ):
        print(token, end="", flush=True)
    print("\n")


async def demo_event_stream():
    """Event streaming — combined token + event streaming for rich UIs."""
    print("=== Event Streaming (tokens + events) ===\n")
    agent = await create_agent(model=llm, name="event-agent")

    async for event in agent.astream_events(
        "What causes rainbows?",
        thread_id="demo-events",
        user_id="demo-user",
    ):
        if event.type == "thinking":
            print(f"[thinking] pattern={event.data.get('output', '')}")
        elif event.type == "token":
            print(event.data["content"], end="", flush=True)
        elif event.type == "llm_call":
            preview = event.data.get("output", "")[:80]
            print(f"\n[llm_call] {event.data.get('name', '')} — {preview}...")
        elif event.type == "tool_call":
            tc_id = event.data.get("id", "")
            print(f"\n[tool_call] {event.data.get('name', '')} [{tc_id}]")
        elif event.type == "tool_result":
            tc_id = event.data.get("id", "")
            print(f"[tool_result] {event.data.get('name', '')} [{tc_id}]: {event.data.get('output', '')[:50]}")
        elif event.type == "done":
            result = event.data["result"]
            print(f"\n\n[done] {result['output'][:120]}...")
        else:
            print(f"\n[{event.type}] {event.data.get('name', '')}")
    print()


async def main():
    await demo_token_stream()
    await demo_event_stream()


if __name__ == "__main__":
    asyncio.run(main())
