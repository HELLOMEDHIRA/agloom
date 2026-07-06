"""Harness example — durable task ledger across turns."""

from __future__ import annotations

import asyncio
import os

from langchain_groq import ChatGroq
from langgraph.store.memory import InMemoryStore

from agloom import create_agent
from agloom.harness.metadata import HarnessMetadata


def _require_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise SystemExit(f"Set {name} to run this example.")
    return v


async def main() -> None:
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    llm = ChatGroq(model=model, api_key=_require_env("GROQ_API_KEY"), temperature=0)

    agent = await create_agent(
        model=llm,
        store=InMemoryStore(),
        harness=True,
        name="harness-demo",
        harness_metadata=HarnessMetadata(
            project_name="demo-rca",
            goal="Investigate elevated API latency",
            init_git=False,
        ),
    )

    r1 = await agent.ainvoke(
        "Start an investigation into checkout API latency spikes",
        thread_id="harness-demo-1",
    )
    print("Turn 1:", r1.pattern_used.value, r1.output[:160])

    r2 = await agent.ainvoke(
        "Summarize what we know so far and list the next verification step",
        thread_id="harness-demo-1",
    )
    print("Turn 2:", r2.pattern_used.value, r2.output[:160])


if __name__ == "__main__":
    asyncio.run(main())
