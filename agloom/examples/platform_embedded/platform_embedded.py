"""Platform embedded recipe — rca-platform style minimal agent."""

from __future__ import annotations

import asyncio
import os

from langchain_groq import ChatGroq
from langgraph.store.memory import InMemoryStore

from agloom import create_agent
from agloom.harness.job_runner import HarnessJobRunner
from agloom.harness.metadata import HarnessMetadata


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Set {name} to run this example.")
    return value


async def main() -> None:
    investigation_id = os.environ.get("INVESTIGATION_ID", "demo-investigation").strip()
    goal = os.environ.get(
        "INVESTIGATION_GOAL",
        "Investigate elevated checkout API latency and identify the likely root cause",
    ).strip()
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    llm = ChatGroq(model=model, api_key=_require_env("GROQ_API_KEY"), temperature=0)

    store = InMemoryStore()
    agent = await create_agent(
        model=llm,
        store=store,
        profile="platform_embedded",
        name="rca-agent",
        harness_metadata=HarnessMetadata(
            project_name=investigation_id,
            goal=goal,
            init_git=False,
        ),
    )

    runner = HarnessJobRunner(job_id=investigation_id, store=store, max_steps=5)
    snap = await runner.run_until_blocked(agent, goal=goal, max_steps=2)
    print("job status:", snap.status)
    print("last step:", snap.last_committed_step)
    print("failure_class:", snap.failure_class)


if __name__ == "__main__":
    asyncio.run(main())
