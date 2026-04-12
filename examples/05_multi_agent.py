"""Multi-agent with shared memory — two agents sharing a LongTermStore.

Both agents read/write to the same long-term memory namespace, allowing
the writer to build on what the researcher discovered.
"""

import asyncio
import os

from langchain_groq import ChatGroq
from langgraph.store.memory import InMemoryStore

from agloom import create_agent

llm = ChatGroq(
    model="meta-llama/llama-4-scout-17b-16e-instruct",
    api_key=os.environ["GROQ_API_KEY"],
    temperature=0,
)


async def main():
    store = InMemoryStore()

    researcher = create_agent(
        model=llm,
        store=store,
        name="researcher",
        system_prompt="You are a research specialist. Provide detailed factual information.",
    )

    writer = create_agent(
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
