# Tool Calling

## Adding Tools

Pass any LangChain-compatible tools to `create_agent`:

```python
from langchain_core.tools import tool

@tool
def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

@tool
def calculate(expression: str) -> str:
    """Evaluate a math expression."""
    return str(eval(expression))

agent = create_agent(
    model=llm,
    tools=[search_web, calculate],
    name="tool-agent",
)
```

When tools are provided and the query needs them, agloom automatically selects the **REACT** pattern.

## Supported Tool Formats

agloom accepts tools in multiple formats:

| Format | Example |
|--------|---------|
| `@tool` decorated function | `@tool def my_fn(x: str) -> str:` |
| `BaseTool` subclass | `class MyTool(BaseTool):` |
| Callable function | `def my_fn(x: str) -> str:` (auto-wrapped) |
| Dict with function | `{"name": "my_tool", "func": my_fn}` |

```python
# All of these work:
agent = create_agent(model=llm, tools=[
    search_web,              # @tool decorated
    MyCustomTool(),          # BaseTool subclass
    lambda x: str(x),       # plain callable (auto-wrapped)
])
```

!!! warning "Unknown types are skipped"
    If you pass something that isn't a tool (e.g., an integer), agloom logs a warning and skips it:
    `normalize_tools: unknown type <class 'int'> — skipped.`

## Reserved Tool Names

agloom uses internal tools for memory and skills. The following names are **reserved** and cannot be used for your tools:

| Reserved Name | Used For |
|--------------|----------|
| `save_memory` | Saving to long-term memory |
| `recall_memory` | Retrieving from long-term memory |
| `load_skill` | Loading a learned skill |

If you try to use a reserved name, `create_agent` raises a `ValueError` immediately:

```python
@tool
def save_memory(data: str) -> str:
    """My custom save."""
    return data

# This raises:
create_agent(model=llm, tools=[save_memory])
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
agent = create_agent(
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

agent = create_agent(
    model=llm,
    tools=[delete_file, read_file],
    interrupt_before_tools=["delete_file"],
    user_callback=approve,
    name="safe-agent",
)
```

See [Human-in-the-Loop](hitl.md) for all 4 interrupt levels.

## Step Tracing for Tools

Every tool call and result is recorded in the step trace with a unique `id` that links call to result:

```python
result = await agent.ainvoke("Calculate 15 * 7")

for step in result.steps:
    tc_id = step.metadata.get("id", "")
    id_str = f" [{tc_id[:8]}]" if tc_id else ""
    print(f"[{step.type.value:12s}] {step.name}{id_str}")
# [classify    ] analyze_query
# [tool_call   ] calculate [tc_abc12]
# [tool_result ] calculate [tc_abc12]  ← same id links call to result
# [llm_call    ] react_agent
```

The `id` field is also available on `tool_call` and `tool_result` events from `astream_events()`, enabling UI elements like spinners that show "calling tool X..." and dismiss when the matching result arrives.
