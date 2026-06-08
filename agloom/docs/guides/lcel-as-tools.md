# LCEL chains and callables as tools

agloom agents use LangChain **tools** (`StructuredTool`, `@tool`, plain callables). Anything you can invoke from Python can be exposed as a tool **without** rewriting it as a LangGraph node first.

## Runnable chains

Wrapping an LCEL **Runnable** (including `prompt | model | parser` chains):

```python
from langchain_core.tools import tool
from langchain_core.runnables import RunnableLambda

chain = prompt | llm | parser  # your LCEL stack

@tool
def run_chain(query: str) -> str:
    """Run the composed chain on free text."""
    out = chain.invoke({"query": query})
    return out if isinstance(out, str) else str(out)
```

Pass **`run_chain`** (or a thin lambda) into **`tools=[...]`** for [`create_agent()`](../concepts/create-agent.md).

## Callable objects

Any **`def`** or **`lambda`** with a docstring can become a tool via **`@tool`** or **`StructuredTool.from_function`**. Use this for:

- Existing business logic (pricing, validation, DB lookups).
- Thin wrappers around HTTP SDKs.
- Adapters that call **`chain.invoke`** / **`chain.batch`** internally.

Keep IO bounded (timeouts, max payload size) — tools run inside the same process as the agent loop.

## Composition vs patterns

agloom’s **nine patterns** handle orchestration (ReAct, supervisor, …). LCEL chains **inside** a tool are implementation detail — they do not replace patterns; they shrink boilerplate for one logical capability.

## See also

- [Tool Calling](../features/tools.md)
- [create_agent API](../concepts/create-agent.md)
