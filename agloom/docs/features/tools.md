# Tool Calling

Give your agent **LangChain-compatible tools**; when a question needs them, agloom routes the turn through the **REACT** pattern (plan → call tools → answer).

!!! tip "Quick start"
    ```python
    agent = await create_agent(model=llm, tools=[my_tool], name="assistant")
    result = await agent.ainvoke("What is 15 * 7?")
    ```

## Adding Tools

Pass any LangChain-compatible tools to `create_agent`:

```python
from langchain_core.tools import tool

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

@tool
def word_count(text: str) -> str:
    """Count whitespace-separated words (safe — never eval user input)."""

    return str(len(text.split()))

async def main():
    agent = await create_agent(
        model=llm,
        tools=[search_web, word_count],
        name="tool-agent",
    )
```

When tools are provided and the query needs them, agloom automatically selects the **REACT** pattern.

## Supported Tool Formats

agloom accepts tools in multiple formats:

| Format                     | Example                                    |
| -------------------------- | ------------------------------------------ |
| `@tool` decorated function | `@tool def my_fn(x: str) -> str:`          |
| `BaseTool` subclass        | `class MyTool(BaseTool):`                  |
| Callable function          | `def my_fn(x: str) -> str:` (auto-wrapped) |
| Dict with function         | `{"name": "my_tool", "func": my_fn}`       |

```python
@tool
def echo_text(x: str) -> str:
    """Return x as string (use @tool or a def with ``__name__`` — plain lambdas become ``callable_tool_<id>``)."""

    return str(x)


async def main():
    # All of these work:
    agent = await create_agent(model=llm, tools=[
        search_web,              # @tool decorated
        MyCustomTool(),          # BaseTool subclass
        echo_text,               # plain callable (auto-wrapped; name from __name__)
    ])
```

!!! warning "Unknown types are skipped"
    If you pass something that isn't a tool (e.g., an integer), agloom logs a warning and skips it:
    `normalize_tools: unknown type <class 'int'> — skipped.`

## Reserved Tool Names

agloom uses internal tools for memory and skills. The following names are **reserved** and cannot be used for your tools:

| Reserved Name   | Used For                         |
| --------------- | -------------------------------- |
| `save_memory`   | Saving to long-term memory       |
| `recall_memory` | Retrieving from long-term memory |
| `load_skill`    | Loading a learned skill          |

If you try to use a reserved name, `create_agent` raises a `ValueError` immediately:

```python
@tool
def save_memory(data: str) -> str:
    """My custom save."""
    return data

# This raises (when awaited in async code):
await create_agent(model=llm, tools=[save_memory])
# ValueError: Tool name(s) save_memory are reserved by agloom
# for internal use. Please rename your tool(s) to avoid conflicts.
# Reserved names: ['load_skill', 'recall_memory', 'save_memory']
```

**Fix:** Rename your tool to something else:

```python
@tool
def store_data(data: str) -> str:  # renamed from save_memory
    """Save data to storage."""
    return data
```

## Disabling Memory Tools

By default, agloom exposes `save_memory` and `recall_memory` as tools the agent can use. To disable this:

```python
async def main():
    agent = await create_agent(
        model=llm,
        tools=[my_tool],
        enable_memory_tools=False,  # no memory tools exposed
        name="no-memory-tools",
    )
```

## Tool Interrupts (HITL)

Pause execution before specific tools are called:

```python
async def approve(context):
    print(f"Tool '{context['tool_name']}' wants to run. Approve? (y/n)")
    return True  # or False to block

async def main():
    agent = await create_agent(
        model=llm,
        tools=[delete_file, read_file],
        interrupt_before_tools=["delete_file"],
        user_callback=approve,
        name="safe-agent",
    )
```

See [Human-in-the-Loop](hitl.md) for all 4 interrupt levels.

## Resilient tool argument types

Models sometimes emit **string numbers**, **stringified JSON objects**, or **`null`** where a tool schema expects `int` or `dict`. When you ship first-party tools with agloom, normalize these cases in the tool body (or a thin wrapper) and return **`Error: ...`** text when conversion is impossible so the model can self-correct.

## Step Tracing for Tools

Every tool call and result is recorded in the step trace with a unique `id` that links call to result:

```python
result = await agent.ainvoke("Calculate 15 * 7")

for step in result.steps:
    tc_id = step.metadata.get("id", "")
    id_str = f" [{tc_id[:8]}]" if tc_id else ""
    print(f"[{step.type.value:12s}] {step.name}{id_str}")
# [classify    ] query_classifier
# [tool_call   ] calculate [tc_abc12]
# [tool_result ] calculate [tc_abc12]  ← same id links call to result
# [llm_call    ] react_agent
```

The `id` field is also available on `tool_call` and `tool_result` events from `astream_events()`, enabling UI elements like spinners that show "calling tool X..." and dismiss when the matching result arrives.
