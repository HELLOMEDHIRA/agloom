# Wire tokens & `metric.tokens`

The module **`agloom.wire_tokens`** bridges **LLM usage** to **AGP / CLI events** without double-counting tokens on a single agent turn.

## Why it exists

Several layers can observe token usage: **ReAct steps**, **streaming chunks**, **`ExecutionResult.token_usage`**, and explicit **`llm_call`** `AgentEvent`s. Frontends and the observability store consume **`metric.tokens`** envelopes. Without coordination, the same usage could be reported more than once.

`wire_tokens` keeps **per-run totals** in the invoke `config` under a private key and:

- **`reset_wire_emitted_usage(config)`** — clear counters at the start of each agent turn.
- **`record_emitted_usage(config, usage)`** — accumulate usage already pushed as **`llm_call`** / metric-related events.
- **`emit_remaining_token_usage(...)`** — emit a final **`metric.tokens`** (via `llm_call` translation in the bridge) for usage not yet attributed on the wire.

Streaming helpers (**`accumulate_stream_usage`**, **`finalize_stream_usage`**) merge **cumulative** provider metadata (e.g. Anthropic) using **component-wise max** so partial chunks do not duplicate totals.

## For integrators

- You rarely need to call these APIs directly; **`create_agent`** and built-in streaming paths wire them in automatically.
- Custom LLM integrations that emit **`llm_call`** events should use the same accounting helpers so **`metric.tokens`** stays consistent (see module docstring in **`agloom.wire_tokens`**).
- Tests: `agloom/tests/test_wire_tokens.py`.

## Related

- [Streaming & Events](streaming.md) — event types and `astream_events`.
- [Observability & LangSmith](observability.md) — LangSmith and structured logging.
- [AGP — Agloom Protocol](../protocol/agp.md) — `metric.*` on the wire.
