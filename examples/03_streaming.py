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
    agent = create_agent(model=llm, name="stream-agent")

    async for token in agent.astream("Explain the Pythagorean theorem in 2 sentences"):
        print(token, end="", flush=True)
    print("\n")


async def demo_event_stream():
    """Event streaming — ChatGPT-style "thinking" visibility."""
    print("=== Event Streaming ===\n")
    agent = create_agent(model=llm, name="event-agent")

    async for event in agent.astream_events("What causes rainbows?"):
        if event.type == "thinking":
            print(f"[thinking] pattern={event.data.get('output', '')}")
        elif event.type == "llm_call":
            preview = event.data.get("output", "")[:80]
            print(f"[llm_call] {event.data.get('name', '')} — {preview}...")
        elif event.type == "done":
            result = event.data["result"]
            print(f"\n[done] {result['output'][:120]}...")
        else:
            print(f"[{event.type}] {event.data.get('name', '')}")
    print()


async def main():
    await demo_token_stream()
    await demo_event_stream()


if __name__ == "__main__":
    asyncio.run(main())
