# Example: Tools & REACT

An agent with custom tools that demonstrates the REACT pattern.

## Code

```python
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
    agent = await create_agent(
        model=llm,
        tools=[calculate, extract_keywords],
        name="tool-agent",
    )

    result = await agent.ainvoke(
        "Use the calculate tool to compute (25 * 4) + 17"
    )

    print(f"Pattern: {result.pattern_used.value}")
    print(f"Output:  {result.output}")
    print("\nStep trace:")
    for step in result.steps:
        print(f"  [{step.type.value:12s}] {step.name} — {step.duration_ms}ms")


asyncio.run(main())
```

## Run it

```bash
python examples/02_tools_and_react.py
```

## Expected output

```
Pattern: REACT
Output:  The result of (25 * 4) + 17 is 117.

Step trace:
  [classify    ] analyze_query — 450ms
  [tool_call   ] calculate — 0ms   (id=call_abc123)
  [tool_result ] calculate — 1ms   (id=call_abc123)
  [llm_call    ] react_agent — 320ms
```

## Key takeaways

- When tools are provided and the query needs them, agloom automatically selects **REACT**
- The step trace shows exactly what happened: classify → tool call → tool result → final LLM call
- Tool call and tool result steps share the same `id` — useful for matching calls to results when multiple tools run in parallel
- You can also use `astream_events()` to see tool calls and token chunks in real time
