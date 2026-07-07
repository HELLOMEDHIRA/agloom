# Context fidelity

Agloom never tail-chops conversation or memory context. When assembled text exceeds the model input budget, the **Context Plane** summarizes or compacts tool payloads — it does not discard the end of a string.

## What is automatic

| Layer | Behavior |
| --- | --- |
| **Session memory** | Oldest turns roll into episodic summary turns when stored tokens exceed ~80% of the model window (or `summarize_max_tokens_budget`). |
| **Prompt injection** | `build_memory_context()` summarizes over-budget text via the session summarizer. |
| **REACT tool loop** | Large tool outputs spill to scratchpad digests; older tool messages compact to stubs under budget pressure. Pre-flight gate fails with `failure_class=context` before HTTP when still over budget. |
| **Scratchpad** | Full payloads stay in-process and optionally spill to LTS (`context/scratchpad/{agent}/{ref}`). Active for **any agent that can run tools** (explicit tools, MCP-only, memory tools, harness) — not only when `tools=` is passed at construction. Use `agloom_recall_tool_artifact` to page. |

## What you configure

- **`profile`** — execution tradeoffs only (`interactive`, `platform_embedded`, …). Not context knobs.
- **`context_window_tokens`** — rare override when inference is wrong.
- **`tool_digest_min_chars`** — lower threshold for scratchpad digests on log-heavy MCP tools (default derived from context window; e.g. `1500`).
- **`summarize_max_tokens_budget`** / **`summarizer_model`** — optional tuning; defaults derive from the chat model.

## Integrator vs Agloom responsibilities

| Concern | Who |
| --- | --- |
| Tool schema has `limit` / pagination | MCP server / tool author (optional) |
| Model uses `limit` when available | Agloom prompts + optional MCP tool description hints |
| Bounding oversized tool **results** on the wire | **Agloom** (always — digest, wire ceiling, pre-flight gate) |
| `RemoteProtocolError` from proxy/gateway | Often symptom of oversized request body; Agloom prefers clear `Context budget exceeded` errors |

When a tool returns `[agloom:tool_digest …]`, use **`agloom_recall_tool_artifact(ref_id, offset, limit)`** to page — do not repeat the same unbounded tool call.

## Removed knobs

There is no `auto_summarize`, `tool_scratchpad`, `context_compact_ratio`, or `max_chars` on `create_agent`. Those behaviors are always on when tools or memory are present.
