# Reflection pattern

**REFLECTION** is one of the nine execution patterns. The classifier selects it for **quality-critical** outputs where an extra **generate → critique → revise** loop pays off (cover letters, specs, polished prose).

Conceptual overview and diagram: [Execution patterns — REFLECTION](../concepts/patterns.md#reflection-generate-critique-revise).

## What happens at runtime

1. **Generator** produces a draft for the user goal.
2. **Critic** scores the draft (**1–10**) and returns **PASSED** or **FEEDBACK** with revision notes.
3. If the score is below **`reflection_threshold`** or the critic did not pass the draft, a **revision** turn runs with the feedback; repeat up to **`max_reflection_iterations`**.
4. Between iterations the runtime respects global halt signals (same as other patterns).

Steps show up in **`ExecutionResult.steps`** and event streams as **`reflection`**-typed **`AgentEvent`** / AGP graph phases where applicable.

## Configuration

| Parameter                       | Default | Meaning                                      |
| ------------------------------- | ------- | -------------------------------------------- |
| **`max_reflection_iterations`** | `3`     | Maximum generate/critique cycles             |
| **`reflection_threshold`**      | `7`     | Minimum critic score (1–10) to stop revising |

Full table: [All parameters](../configuration/parameters.md).

## When you might not see REFLECTION

- The **classifier** must route to **`PatternType.REFLECTION`** — prompts that look like quick factual questions usually land on **DIRECT** or **REACT**.
- **MCP / observability fetch** queries (logs, metrics, traces, incident investigation) with **`mcp_servers`** configured are routed to **REACT**, not REFLECTION — a raw data fetch is not a generate→critique loop. See [MCP classifier routing](mcp.md#classifier-routing-with-mcp).
- **Subtasks**: the classifier should provide exactly one goal in **`analysis.subtasks`**. If it returns REFLECTION with an empty list, agloom **synthesizes a goal from the user query** (same worker id `goal`) and continues the critique loop. A hard failure only occurs when both subtasks and the query text are empty.

## Human-in-the-loop

You can gate the pattern with HITL middleware (e.g. interrupt after **`REFLECTION`**) — [Human-in-the-loop](hitl.md).

## See also

- [Streaming & events](streaming.md) — **`reflection`** row in the event table
- [Memory](memory.md) — pattern/cache notes for REFLECTION
