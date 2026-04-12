"""Basic agent — simplest possible create_agent + ainvoke usage."""

import asyncio
import os

from langchain_groq import ChatGroq

from agloom import create_agent

llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.environ["GROQ_API_KEY"],
    temperature=0,
)


async def main():
    agent = create_agent(model=llm, name="basic-agent")

    result = await agent.ainvoke("What are the three laws of thermodynamics?")

    print(f"Pattern: {result.pattern_used.value}")
    print(f"Steps:   {len(result.steps)}")
    print(f"Tokens:  {result.token_usage}")
    print(f"\n{result.output}")


if __name__ == "__main__":
    asyncio.run(main())
