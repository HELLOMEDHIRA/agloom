"""Agent with custom tools — demonstrates REACT pattern with tool calling."""

import asyncio
import os

from langchain_core.tools import tool
from langchain_groq import ChatGroq

from agloom import create_agent

llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.environ["GROQ_API_KEY"],
    temperature=0,
)


@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression and return the result."""
    return str(eval(expression))


@tool
def extract_keywords(text: str) -> str:
    """Extract key words from the given text."""
    stop = {"the", "a", "an", "is", "are", "was", "in", "on", "at", "to", "and", "or", "of"}
    words = [w.strip(".,!?") for w in text.lower().split() if len(w) > 2]
    return ", ".join(sorted({w for w in words if w not in stop}))


async def main():
    agent = create_agent(
        model=llm,
        tools=[calculate, extract_keywords],
        name="tool-agent",
    )

    result = await agent.ainvoke("Use the calculate tool to compute (25 * 4) + 17")

    print(f"Pattern: {result.pattern_used.value}")
    print(f"Output:  {result.output}")
    print("\nStep trace:")
    for step in result.steps:
        print(f"  [{step.type.value:12s}] {step.name} — {step.duration_ms}ms")


if __name__ == "__main__":
    asyncio.run(main())
