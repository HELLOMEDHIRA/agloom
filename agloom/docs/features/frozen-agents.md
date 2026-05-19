# Frozen Agents

## The Problem

Query classification adds ~200–500ms per call. For batch workloads with the same agent role, that overhead adds up fast.

## The Solution

**Frozen agents** classify **once** on the first `ainvoke` / `astream` call, lock the **classifier-derived execution plan** (pattern, subtasks, orchestration depth, dispatch vs handler), then **replay** that plan on every later call with new user messages only.

Invoke shape matches **LangChain `create_agent`**:

```python
agent = await create_agent(
    model=llm,
    frozen=True,
    system_prompt="Translate the following text to French.",
    name="translator",
)

# First call — classify + lock plan + execute
await agent.ainvoke({"messages": [{"role": "user", "content": "Hello"}]})

# Later calls — same API, no re-classify
await agent.ainvoke({"messages": [{"role": "user", "content": "Bonjour"}]})
await agent.ainvoke("Good morning")  # string sugar
```

Fixed instructions live in `system_prompt` (or the default prompt). Each invoke only supplies a new **user** message.

## What gets locked (classifier-derived)

Everything structural comes from the **first** `analyze_query` result:

| Locked artifact | Source |
| --------------- | ------ |
| Root pattern | Classifier `QueryAnalysis.pattern` |
| Subtasks (worker ids, tasks, tools, deps) | Classifier `QueryAnalysis.subtasks` |
| Orchestration depth / token & LLM budgets | Classifier + `resolve_turn_orchestration` |
| Handler vs root `dispatch_pattern` | `max_pattern_depth` ceiling + locked analysis |
| Child spawn **routing** | Same locked `analysis` passed into `dispatch_pattern` / handlers |

On **replay** (turn 2+), agloom still runs LLMs, tools, and workers with the **new user message**, but it does **not**:

- Re-run root classification
- Run `check_escalation` to add **new** child patterns
- `reclassify_subtask` for dynamic DAG / sequential nodes
- Failure/conflict recovery spawns that would discover a new topology

Turn 1 may still grow a spawn tree (escalation, dynamic nodes, recovery) according to your agent config; that tree is driven by the **same** locked classifier output on every replay.

### With recursive orchestration

If the first call locks `execution_mode="dispatch"` (`max_pattern_depth > 0` and classifier allows depth), later calls enter `dispatch_pattern` again with the **same** `QueryAnalysis`, not a new classify. Set `max_pattern_depth=0` (default) for simple single-handler frozen batch jobs.

## Configuration

| Parameter             | Default | Description |
| --------------------- | ------- | ----------- |
| `frozen`              | `False` | Enable frozen mode |
| `frozen_analysis_ttl` | `0`     | Re-classify after N seconds (`0` = never) |

Call `agent.reset_frozen()` to force a new lock on the next turn. Semantic query cache is **off by default** when `frozen=True`.

## Streaming

Same input as `ainvoke`:

```python
async for event in agent.astream_events(
    {"messages": [{"role": "user", "content": "Hello"}]}
):
    ...
```

## All entry points

`ainvoke`, `invoke`, `astream`, `stream`, `astream_events`, `astream_agp_events`, and `abatch` use the same normalization and frozen rules.

## Batch processing

Put **fixed** task wording in `system_prompt`. Each item only supplies a new user message:

```python
agent = await create_agent(
    model=llm,
    frozen=True,
    system_prompt=(
        "Translate the user's message from English to French. "
        "Source language: English. Target language: French."
    ),
)

# First call — classifies once and locks routing
await agent.ainvoke({"messages": [{"role": "user", "content": "Hello"}]})

for text in texts:
    await agent.ainvoke({"messages": [{"role": "user", "content": text}]})
```

Or `abatch`:

```python
await agent.abatch(
    [{"messages": [{"role": "user", "content": t}]} for t in texts],
    max_concurrent=8,
)
```

If concurrent `abatch` items race on the **first** batch, whichever finishes first wins the frozen lock. For a predictable lock, run one warm-up `ainvoke` first, or use `max_concurrent=1` on the first batch.

Call `reset_frozen()` when you change the job (`system_prompt` or a new agent instance).
