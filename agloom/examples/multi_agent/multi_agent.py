"""Multi-agent with shared memory — two agents sharing a LongTermStore.

Both agents read/write to the same long-term memory namespace, allowing
the writer to build on what the researcher discovered.

Requires ``langchain-groq`` (``pip install langchain-groq``) and ``GROQ_API_KEY``.
"""

from __future__ import annotations

import asyncio
import os

from langchain_groq import ChatGroq
from langgraph.store.memory import InMemoryStore

from agloom import create_agent


def _require_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"Set {name} (e.g. export {name}=...) to run this example.")
    return v


def _groq_llm() -> ChatGroq:
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    return ChatGroq(model=model, api_key=_require_env("GROQ_API_KEY"), temperature=0)


async def main():
    store = InMemoryStore()
    llm = _groq_llm()

    researcher = await create_agent(
        model=llm,
        store=store,
        name="researcher",
        system_prompt="You are a research specialist. Provide detailed factual information.",
    )

    writer = await create_agent(
        model=llm,
        store=store,
        name="writer",
        system_prompt="You are a concise writer. Summarize information clearly in 2-3 sentences.",
    )

    print("=== Researcher ===")
    r1 = await researcher.ainvoke(
        "What are the main benefits of renewable energy?",
        user_id="demo-user",
    )
    print(f"Pattern: {r1.pattern_used.value}")
    print(f"Output:  {r1.output[:200]}...\n")

    print("=== Writer ===")
    r2 = await writer.ainvoke(
        "Summarize the key points about renewable energy benefits",
        user_id="demo-user",
    )
    print(f"Pattern: {r2.pattern_used.value}")
    print(f"Output:  {r2.output[:200]}...\n")

    print("=== Batch Processing ===")
    # ``abatch`` runs each query on its own thread id prefix so checkpoints never collide.
    results = await researcher.abatch(
        [
            "What is solar energy?",
            "What is wind energy?",
            "What is hydroelectric power?",
        ],
        max_concurrent=3,
        user_id="demo-user",
    )
    for r in results:
        print(f"  [{r.pattern_used.value}] {r.output[:80]}...")


if __name__ == "__main__":
    asyncio.run(main())
