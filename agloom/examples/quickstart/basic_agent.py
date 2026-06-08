"""Basic agent — simplest possible create_agent + ainvoke usage.

Requires ``langchain-groq`` (``pip install langchain-groq``) and ``GROQ_API_KEY``.
Override the default model with ``GROQ_MODEL`` if your account uses a different id.
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


async def main() -> None:
    agent = await create_agent(model=_groq_llm(), name="basic-agent")

    result = await agent.ainvoke("What are the three laws of thermodynamics?")

    print(f"Pattern: {result.pattern_used.value}")
    print(f"Steps:   {len(result.steps)}")
    print(f"Tokens:  {result.token_usage}")
    print(f"\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
