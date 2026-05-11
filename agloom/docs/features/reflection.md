# Reflection pattern

**REFLECTION** is one of the nine execution patterns. The classifier selects it for **quality-critical** outputs where an extra **generate → critique → revise** loop pays off (cover letters, specs, polished prose).

Conceptual overview and diagram: [Execution patterns — REFLECTION](../concepts/patterns.md#reflection-generate-critique-revise).

## What happens at runtime

1. **Generator** produces a draft for the user goal.
2. **Critic** scores the draft (**1–10**) and returns structured **`PASSED`** / **`FEEDBACK`** (see **`agloom/patterns/reflection.py`** prompts).
3. If the score is below **`reflection_threshold`** or the critic did not pass the draft, a **revision** turn runs with the feedback; repeat up to **`max_reflection_iterations`**.
4. Between iterations the runtime respects global halt signals (same as other patterns).

Steps show up in **`ExecutionResult.steps`** and event streams as **`reflection`**-typed **`AgentEvent`** / AGP graph phases where applicable.

## Configuration

| Parameter | Default | Meaning |
| --- | --- | --- |
| **`max_reflection_iterations`** | `3` | Maximum generate/critique cycles |
| **`reflection_threshold`** | `7` | Minimum critic score (1–10) to stop revising |

Full table: [All parameters](../configuration/parameters.md).

## When you might not see REFLECTION

- The **classifier** must route to **`PatternType.REFLECTION`** — prompts that look like quick factual questions usually land on **DIRECT** or **REACT**.
- **Subtasks**: the reflection handler expects classifier output with a usable goal in **`analysis.subtasks`**; if empty, you get a short fallback message (see source).

## Human-in-the-loop

You can gate the pattern with HITL middleware (e.g. interrupt after **`REFLECTION`**) — [Human-in-the-loop](hitl.md).

## See also

- [Streaming & events](streaming.md) — **`reflection`** row in the event table
- [Memory](memory.md) — pattern/cache notes for REFLECTION
