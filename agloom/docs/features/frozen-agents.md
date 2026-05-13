# Frozen Agents

## The Problem

Query classification adds ~200-500ms per call. For batch workloads where you're processing thousands of items with the same structure, that overhead adds up fast.

## The Solution

**Frozen agents** classify once on the first call and reuse the cached analysis for every subsequent call.

```python
async def main():
    agent = await create_agent(
        model=llm,
        frozen=True,
        frozen_template="Translate to French: {text}",
        input_key="text",
        name="translator",
    )

    # First call — classifies, caches the result
    r1 = await agent.ainvoke({"text": "Hello world"})        # ~700ms

    # Subsequent calls — skip classification
    r2 = await agent.ainvoke({"text": "Good morning"})        # ~300ms
    r3 = await agent.ainvoke({"text": "Thank you"})           # ~300ms
```

## How It Works

```mermaid
sequenceDiagram
    participant User
    participant Agent
    participant Classifier
    participant LLM

    User->>Agent: ainvoke({"text": "Hello"})
    Agent->>Classifier: Classify (first time)
    Classifier-->>Agent: DIRECT pattern
    Agent->>Agent: Cache analysis
    Agent->>LLM: Execute
    LLM-->>User: Result

    User->>Agent: ainvoke({"text": "World"})
    Agent->>Agent: Use cached analysis
    Agent->>LLM: Execute (skip classify)
    LLM-->>User: Result
```

## Configuration

| Parameter             | Type    | Default    | Description                        |                     |
| --------------------- | ------- | ---------- | ---------------------------------- | ------------------- |
| `frozen`              | `bool`  | `False`    | Enable frozen mode                 |                     |
| `frozen_template`     | `str`   | required   | Template with `{key}` placeholders |                     |
| `input_key`           | `str \  | list[str]` | `"input"`                          | Placeholder name(s) |
| `frozen_analysis_ttl` | `float` | `0`        | Cache TTL in seconds (0 = never)   |                     |

## Multiple Placeholders

```python
async def main():
    agent = await create_agent(
        model=llm,
        frozen=True,
        frozen_template="Translate '{text}' from {source} to {target}",
        input_key=["text", "source", "target"],
        name="multi-translator",
    )

    result = await agent.ainvoke({
        "text": "Hello",
        "source": "English",
        "target": "Japanese",
    })
```

## TTL (Time-to-Live)

Force re-classification after a period:

```python
async def main():
    agent = await create_agent(
        model=llm,
        frozen=True,
        frozen_template="Summarize: {text}",
        input_key="text",
        frozen_analysis_ttl=3600,  # re-classify after 1 hour
        name="summarizer",
    )
```

## String Inputs

Frozen agents also accept plain strings — they're mapped to the `input_key`:

```python
async def main():
    agent = await create_agent(
        model=llm,
        frozen=True,
        frozen_template="Classify sentiment: {input}",
        name="sentiment",
    )

    result = await agent.ainvoke("I love this product!")  # input_key defaults to "input"
```

## Validation Errors

When **awaited**, invalid frozen configuration raises clear errors:

- `await create_agent(model=llm, frozen=True)` → `ValueError`: `frozen=True` requires non-empty `frozen_template`
- `await create_agent(model=llm, frozen=True, frozen_template="No placeholder", input_key="text")` — builds, but `{text}` is not substituted if missing from the template
- `await create_agent(model=llm, frozen=True, frozen_template="{x}", input_key=[])` → `ValueError`: `frozen=True` requires non-empty `input_key`

## Batch Processing

Combine frozen agents with `abatch` for maximum throughput:

```python
async def main():
    texts = ["Hello", "World", "Python", "AI", ...]  # thousands of items

    results = await agent.abatch(
        [{"text": t} for t in texts],
        max_concurrent=8,
    )
```
