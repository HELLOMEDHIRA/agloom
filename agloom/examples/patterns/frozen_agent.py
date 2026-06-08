"""Frozen agent — classify once, reuse the pattern for every subsequent call.

Ideal for batch/template workloads where system_prompt and structure are fixed
and only the input data changes. Saves ~200-500ms per call by skipping
re-classification.

Requires ``langchain-groq`` (``pip install langchain-groq``) and ``GROQ_API_KEY``.
"""

import asyncio
import os
import time

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


async def main():
    agent = await create_agent(
        model=_groq_llm(),
        frozen=True,
        system_prompt="Translate the following text to French.",
        name="translator",
    )

    inputs = [
        "Good morning, how are you?",
        "The weather is beautiful today.",
        "I would like a cup of coffee, please.",
    ]

    t0 = time.perf_counter()
    for text in inputs:
        result = await agent.ainvoke({"messages": [{"role": "user", "content": text}]})
        print(f"  EN: {text}")
        print(f"  FR: {result.output}")
        print(f"  Pattern: {result.pattern_used.value}")
        print()

    elapsed = round((time.perf_counter() - t0) * 1000)
    print(f"Total: {len(inputs)} translations in {elapsed}ms")
    print("(First call classifies; subsequent calls reuse the cached pattern)")


if __name__ == "__main__":
    asyncio.run(main())
