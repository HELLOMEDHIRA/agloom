# Task Delegation

agloom provides four composable delegation patterns that let agents hand off work to other agents. All four can be mixed within the same parent agent.

## Overview

| Pattern | Mechanism | Use Case |
| --- | --- | --- |
| **as_tool()** | Agent wrapped as a LangChain tool | Parent calls child via tool loop |
| **register_handoff()** | Transparent classifier-driven routing | Auto-route queries to specialists |
| **delegates=[]** | Hierarchical delegation at creation | Pre-configured child agents |
| **adelegate_background()** | Fire-and-forget async tasks | Long-running background work |

## Pattern 1: Agent as Tool — `as_tool()`

Wrap any agent as a standard LangChain tool. The parent agent calls it through its normal tool loop (REACT, SUPERVISOR, etc.).

```python
from agloom import create_agent

async def main():
    # Create specialist agents
    researcher = await create_agent(model=llm, name="researcher", tools=[search_tool])
    coder = await create_agent(model=llm, name="coder", tools=[run_code])

    # Parent uses them as tools
    parent = await create_agent(
        model=llm,
        name="coordinator",
        tools=[
            researcher.as_tool(description="Research academic papers and summarize findings"),
            coder.as_tool(description="Write and execute Python code"),
        ],
    )

    result = await parent.ainvoke("Find the latest paper on RLHF and implement the algorithm")
```

### Custom tool name

```python
tool = agent.as_tool(
    name="research_tool",
    description="Search and summarize academic papers",
)
```

## Pattern 2: Transparent Hand-off — `register_handoff()`

Register delegates that the classifier can route to automatically. The hand-off is transparent — the caller receives the delegate's result as if the parent handled it.

```python
async def main():
    researcher = await create_agent(model=llm, name="researcher", tools=[search_tool])
    coder = await create_agent(model=llm, name="coder", tools=[run_code])

    parent = await create_agent(model=llm, name="coordinator")
    parent.register_handoff(researcher, description="Research and summarize academic papers")
    parent.register_handoff(coder, description="Write, review, and debug code")

    # Classifier sees delegate descriptions and routes automatically
    result = await parent.ainvoke("Find papers about transformer architectures")
    # → routed to researcher transparently
```

### Conditional hand-off with filter_fn

```python
parent.register_handoff(
    coder,
    description="Write code",
    filter_fn=lambda q: any(kw in q.lower() for kw in ["code", "implement", "debug"]),
)
```

### Query transformation

```python
parent.register_handoff(
    researcher,
    description="Research papers",
    input_transform=lambda q: f"Search academic databases for: {q}",
)
```

### Using HandoffTarget directly

```python
from agloom import HandoffTarget

target = HandoffTarget(
    researcher,
    name="paper_search",
    description="Search and summarize academic papers",
    filter_fn=lambda q: "paper" in q.lower(),
    input_transform=lambda q: f"Find papers about: {q}",
)
parent.register_handoff(target)
```

## Pattern 3: Hierarchical Delegation — `delegates=[]`

Pass delegate agents at creation time. They become available for both transparent hand-off (classifier routing) and explicit delegation via `adelegate()`.

```python
async def main():
    researcher = await create_agent(model=llm, name="researcher", tools=[search_tool])
    coder = await create_agent(model=llm, name="coder", tools=[run_code])

    parent = await create_agent(
        model=llm,
        name="coordinator",
        delegates=[researcher, coder],
    )

    # Explicit delegation
    result = await parent.adelegate("Find RLHF papers", delegate_name="researcher")

    # Or let the classifier route automatically
    result = await parent.ainvoke("Find papers about transformers")
```

### With HandoffTarget for fine-grained control

```python
async def main():
    parent = await create_agent(
        model=llm,
        name="coordinator",
        delegates=[
            HandoffTarget(researcher, description="Academic paper search and analysis"),
            HandoffTarget(coder, description="Code generation and debugging"),
        ],
    )
```

## Pattern 4: Background Delegation — `adelegate_background()`

Fire-and-forget delegation for long-running tasks. Returns a `task_id` immediately.

```python
async def main():
    parent = await create_agent(model=llm, name="coordinator", delegates=[researcher])

    # Submit background task
    task_id = await parent.adelegate_background(
        "Comprehensive literature review on quantum computing",
        delegate_name="researcher",
    )
    print(f"Task submitted: {task_id}")

    # Do other work...
    result = await parent.ainvoke("What is 2+2?")

    # Check status
    bg = parent.background_status(task_id)
    print(f"Status: {bg.status}")  # pending, running, completed, failed, cancelled

    # Wait for result when ready
    result = await parent.await_background(task_id, timeout=120.0)
    print(result.output)

    # Cancel if needed
    await parent.cancel_background(task_id)
```

### Managing background tasks

```python
# List all background tasks (newest first)
mgr = parent.config["_bg_delegation_manager"]
for task in mgr.list_tasks():
    print(f"{task.task_id[:8]}… {task.target_name} → {task.status.value}")

# Cleanup old completed tasks (default: older than 1 hour)
removed = mgr.cleanup(max_age_seconds=3600)
```

## Combining Patterns

All four patterns work together on the same parent agent:

```python
async def main():
    researcher = await create_agent(model=llm, name="researcher", tools=[search_tool])
    coder = await create_agent(model=llm, name="coder", tools=[run_code])
    reviewer = await create_agent(model=llm, name="reviewer")

    parent = await create_agent(
        model=llm,
        name="coordinator",
        # Pattern 1: coder available as a tool in the parent's tool loop
        tools=[coder.as_tool(description="Write code")],
        # Pattern 3: researcher as hierarchical delegate
        delegates=[researcher],
    )

    # Pattern 2: reviewer as transparent handoff
    parent.register_handoff(reviewer, description="Review and critique documents")

    # Pattern 4: long-running background research
    task_id = await parent.adelegate_background(
        "Deep literature review on RLHF",
        delegate_name="researcher",
    )

    # Meanwhile, parent handles queries using its tools + handoffs
    result = await parent.ainvoke("Review this document for quality")
    # → transparently handed off to reviewer
```

## API Reference

### HandoffTarget

```python
HandoffTarget(
    agent,                              # UnifiedAgent instance
    name=None,                          # Display name (defaults to agent.name)
    description="",                     # What this delegate specializes in
    filter_fn=None,                     # Optional (query) → bool predicate
    input_transform=None,               # Optional (query) → query transform
)
```

### UnifiedAgent delegation methods

| Method | Returns | Description |
| --- | --- | --- |
| `as_tool(name=, description=)` | `BaseTool` | Wrap agent as LangChain tool |
| `register_handoff(target, ...)` | `None` | Register transparent hand-off target |
| `adelegate(query, delegate_name=)` | `ExecutionResult` | Explicit async delegation |
| `adelegate_background(query, ...)` | `str` (task_id) | Fire-and-forget background delegation |
| `await_background(task_id, timeout=)` | `ExecutionResult \| None` | Wait for background result |
| `background_status(task_id)` | `BackgroundTask \| None` | Check background task status |
| `cancel_background(task_id)` | `bool` | Cancel a running background task |

### BackgroundTaskStatus

| Value | Description |
| --- | --- |
| `pending` | Task created but not yet started |
| `running` | Task is currently executing |
| `completed` | Task finished successfully |
| `failed` | Task failed with an error |
| `cancelled` | Task was cancelled |
