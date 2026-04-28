"""Frozen agent — classify once, reuse the pattern for every subsequent call.

Ideal for batch/template workloads where system_prompt and structure are fixed
and only the input data changes. Saves ~200-500ms per call by skipping
re-classification.
"""

import asyncio
import os
import time

from langchain_groq import ChatGroq

from agloom import create_agent

llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.environ["GROQ_API_KEY"],
    temperature=0,
)


async def main():
    agent = await create_agent(
        model=llm,
        frozen=True,
        frozen_template="Translate the following text to French: {text}",
        input_key="text",
        name="translator",
    )

    inputs = [
        "Good morning, how are you?",
        "The weather is beautiful today.",
        "I would like a cup of coffee, please.",
    ]

    t0 = time.perf_counter()
    for text in inputs:
        result = await agent.ainvoke({"text": text})
        print(f"  EN: {text}")
        print(f"  FR: {result.output}")
        print(f"  Pattern: {result.pattern_used.value}")
        print()

    elapsed = round((time.perf_counter() - t0) * 1000)
    print(f"Total: {len(inputs)} translations in {elapsed}ms")
    print("(First call classifies; subsequent calls reuse the cached pattern)")


if __name__ == "__main__":
    asyncio.run(main())
