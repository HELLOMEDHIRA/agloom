# Wire tokens & `metric.tokens`

When you build a **chat UI** or **observability dashboard**, you need trustworthy token counts on the wire — without the same usage reported twice in one turn.

---

## What you see on the wire

During a turn, the runtime may emit one or more **`metric.tokens`** events:

```json
{
  "type": "metric.tokens",
  "data": {
    "input_tokens": 1200,
    "output_tokens": 340,
    "model": "groq:llama-3.3-70b-versatile",
    "phase": "react"
  }
}
```

| Field | Meaning |
| ----- | ------- |
| `input_tokens` | Prompt / context tokens for this slice |
| `output_tokens` | Completion tokens for this slice |
| `phase` | Optional label (classifier, react, worker, …) |
| `model` | Model id when known |

---

## How agloom keeps counts honest

A single turn can touch many LLM calls (classifier, ReAct steps, workers, summarizer). agloom **aggregates usage internally** and emits **`metric.tokens`** so that:

- Streaming UIs can show running totals in the sidebar
- Clients do not double-count when both step events and final results carry usage
- Providers that send **cumulative** usage in stream metadata are merged correctly

You do **not** configure this — it is automatic for `create_agent`, `astream_events`, `astream_agp_events`, and `agloom-runtime`.

---

## Building a token footer in your UI

**Per-turn rollup (recommended):** track the latest `metric.tokens` for the active turn, or sum only events whose `phase` you care about. The official CLI shows **`↑input ↓output`** style labels derived from these events.

**Session totals:** accumulate across turns in your client state; reset when `session.closed` fires.

**Do not** sum every `metric.tokens` event blindly if your client also adds `ExecutionResult.token_usage` at the end — pick one source of truth per turn. The library aligns wire metrics with `result.token_usage` when the turn completes.

---

## Related

- [Thinking trace & reasoning streams](thinking-events.md)
- [Streaming & events](streaming.md)
- [Observability & LangSmith](observability.md)
- [AGP — `metric.tokens`](../protocol/agp.md)
