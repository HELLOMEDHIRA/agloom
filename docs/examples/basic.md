# Example: Basic Agent

The simplest possible agloom agent.

## Code

```python
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
    agent = await create_agent(model=llm, name="basic-agent")

    result = await agent.ainvoke("What are the three laws of thermodynamics?")

    print(f"Pattern: {result.pattern_used.value}")
    print(f"Steps:   {len(result.steps)}")
    print(f"Tokens:  {result.token_usage}")
    print(f"\n{result.output}")


asyncio.run(main())
```

## Run it

```bash
export GROQ_API_KEY="gsk_..."  # pragma: allowlist secret
python examples/01_basic_agent.py
```

## Expected output

```
Pattern: DIRECT
Steps:   2
Tokens:  {'input_tokens': 48, 'output_tokens': 256, 'total_tokens': 304}

The three laws of thermodynamics are:
1. Energy cannot be created or destroyed...
2. Entropy of an isolated system always increases...
3. As temperature approaches absolute zero...
```

## What happened

1. `create_agent` created the agent with default settings (session memory auto-created)
2. The classifier analyzed "What are the three laws of thermodynamics?" → simple factual query → **DIRECT** pattern
3. One LLM call was made
4. The result includes the response, pattern used, step trace, and token usage

## Adding conversation memory

Pass `thread_id` to maintain context across calls:

```python
async def chat_example():
    agent = await create_agent(model=llm, name="chat-agent")

    # First turn
    r1 = await agent.ainvoke("My name is Alice", thread_id="chat-1")
    print(r1.output)

    # Second turn — agent remembers because same thread_id
    r2 = await agent.ainvoke("What's my name?", thread_id="chat-1")
    print(r2.output)  # → "Your name is Alice"
```

Without `thread_id`, each call gets a random ID and can't find previous turns.
