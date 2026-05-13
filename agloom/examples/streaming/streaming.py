"""Streaming — ``astream`` text chunks vs AGP wire events via ``astream_agp_events``.

``astream_events`` yields in-process :class:`~agloom.models.AgentEvent` objects
(thinking, tool_call, token, …). For the **same typed envelopes** the runtime emits on
the AGP wire (``token.delta``, ``session.opened``, …), use ``astream_agp_events``.

Requires ``langchain-groq`` (``pip install langchain-groq``) and ``GROQ_API_KEY``.
"""

from __future__ import annotations

import asyncio
import os

from langchain_groq import ChatGroq

from agloom import create_agent


def _require_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"Set {name} (e.g. export {name}=...) to run this example.")
    return v


def _groq_llm() -> ChatGroq:
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    return ChatGroq(model=model, api_key=_require_env("GROQ_API_KEY"), temperature=0)


async def demo_astream_chunks() -> None:
    """Iterator of text chunks (see ``UnifiedAgent.astream`` docstring for DIRECT vs simulated)."""
    print("=== astream() — text chunks ===\n")
    agent = await create_agent(model=_groq_llm(), name="stream-agent")

    async for chunk in agent.astream(
        "Explain the Pythagorean theorem in 2 sentences",
        thread_id="demo-session",
    ):
        print(chunk, end="", flush=True)
    print("\n")


async def demo_agp_wire() -> None:
    """Typed AGP envelopes (what ``agloom-runtime`` would serialize to NDJSON)."""
    print("=== astream_agp_events() — AGP wire types ===\n")
    agent = await create_agent(model=_groq_llm(), name="agp-stream-agent")

    async for evt in agent.astream_agp_events(
        "What causes rainbows? Answer in one short paragraph.",
        thread_id="demo-agp",
        session_id="demo-agp-session",
    ):
        if evt.type == "session.opened":
            print(f"[{evt.type}] session={evt.session!r} thread={evt.thread!r}")
        elif evt.type == "token.delta":
            print(evt.data.text, end="", flush=True)
        elif evt.type == "metric.tokens":
            print(
                f"\n[{evt.type}] in={evt.data.input_tokens} out={evt.data.output_tokens}",
                flush=True,
            )
        elif evt.type == "session.closed":
            print(f"\n[{evt.type}] reason={evt.data.reason!r}")
        elif evt.type.startswith("tool.") or evt.type.startswith("thinking"):
            # Keep noise low; print these if you want a full trace.
            pass
        else:
            print(f"\n[{evt.type}]", flush=True)


async def main() -> None:
    await demo_astream_chunks()
    await demo_agp_wire()


if __name__ == "__main__":
    asyncio.run(main())
