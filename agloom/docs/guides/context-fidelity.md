# Context fidelity

Agloom never tail-chops conversation or memory context. When assembled text exceeds the model input budget, the **Context Plane** summarizes or compacts tool payloads — it does not discard the end of a string.

## What is automatic

| Layer | Behavior |
| --- | --- |
| **Session memory** | Oldest turns roll into episodic summary turns when stored tokens exceed ~80% of the model window (or `summarize_max_tokens_budget`). |
| **Prompt injection** | `build_memory_context()` summarizes over-budget text via the session summarizer. |
| **REACT tool loop** | Large tool outputs spill to scratchpad digests; older tool messages compact to stubs under budget pressure. |
| **Scratchpad** | Full payloads stay in-process and optionally spill to LTS (`context/scratchpad/{agent}/{ref}`). Use `recall_tool_artifact`. |

## What you configure

- **`profile`** — execution tradeoffs only (`interactive`, `platform_embedded`, …). Not context knobs.
- **`context_window_tokens`** — rare override when inference is wrong.
- **`summarize_max_tokens_budget`** / **`summarizer_model`** — optional tuning; defaults derive from the chat model.

## Removed knobs

There is no `auto_summarize`, `tool_scratchpad`, `context_compact_ratio`, or `max_chars` on `create_agent`. Those behaviors are always on when tools or memory are present.
