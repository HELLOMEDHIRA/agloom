# Example: Frozen / Batch Agent

Frozen agents classify once and reuse the cached pattern for every subsequent call — ideal for batch workloads.

## Code

```python
"""Frozen agent — classify once, reuse forever."""

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
    agent = create_agent(
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
        print()

    elapsed = round((time.perf_counter() - t0) * 1000)
    print(f"Total: {len(inputs)} translations in {elapsed}ms")


asyncio.run(main())
```

## Batch Processing

For maximum throughput, combine `frozen=True` with `abatch`:

```python
async def batch_example():
    texts = [
        "Hello", "World", "Python", "Artificial Intelligence",
        "Machine Learning", "Deep Learning", "Neural Networks",
    ]

    results = await agent.abatch(
        [{"text": t} for t in texts],
        max_concurrent=4,  # 4 parallel LLM calls
    )

    for text, result in zip(texts, results):
        print(f"  {text} → {result.output}")
```

## Run it

```bash
python examples/04_frozen_agent.py
```

## Performance comparison

| Mode | Classification | Per-call overhead |
|------|---------------|------------------|
| Normal | Every call (~300-500ms) | Higher |
| Frozen | First call only | ~0ms after first |

For 1000 translations, frozen mode saves ~300-500 seconds of classification time.
