# Agloom Protocol (AGP) — v1

**Status:** **AGP v1 is stable** — the envelope (`v`, `id`, `ts`, `session`, `thread`, `seq`, `type`, `data`) and the event types listed below are implemented in `agloom.protocol` and emitted by **`agloom-runtime serve`** (stdio or WebSocket). **agloom CLI**, the web workspace, and other clients consume the same stream.

New **event types** and optional **payload fields** evolve **additively** (consumers must tolerate unknown `type` values). Domains **`skill.*`** and **`prompt.*`** are part of v1 (see below). A breaking wire change would ship as **`v="2"`**, not under v1.

AGP is UI-agnostic and transport-agnostic. This page is the wire-format reference; see **`agloom/docs/runtime/architecture.md`** for runtime layout.

> **Docs nav:** Older builds labeled this section “experimental”; that referred to early rollout, not the current contract. Treat **v1** as the supported specification.

---

## Wire format

One JSON object per line (NDJSON over stdio; one frame per WebSocket message when `--transport=ws`). Every event carries the same envelope; the `type` field discriminates the payload schema.

```json
{
  "v": "1",
  "id": "evt_01HX9R7M5K8WJ5Z9",
  "ts": "2026-05-08T10:23:45.123456+00:00",
  "session": "sess_abc123",
  "thread": "thread_xyz",
  "seq": 4,
  "type": "thinking.step",
  "data": { "step": "analyze_query", "elapsed_ms": 120 }
}
```

| Field     | Type            | Required | Notes                                                           |                                                 |
| --------- | --------------- | -------- | --------------------------------------------------------------- | ----------------------------------------------- |
| `v`       | `"1"`           | yes      | Major protocol version. Bumped only on breaking schema changes. |                                                 |
| `id`      | `string`        | yes      | Opaque, time-ordered-ish unique id (currently `evt_<24 hex>`).  |                                                 |
| `ts`      | ISO-8601 string | yes      | Aware UTC timestamp.                                            |                                                 |
| `session` | `string`        | yes      | Session id; stable across reconnects.                           |                                                 |
| `thread`  | `string`        | yes      | LangGraph thread id (resume key).                               |                                                 |
| `seq`     | `int >= 0`      | yes      | Monotonic per session — gap detection.                          |                                                 |
| `parent`  | `string \       | null`    | no                                                              | Causal parent event id.                         |
| `trace`   | `string \       | null`    | no                                                              | OpenTelemetry trace id when tracing is enabled. |
| `type`    | `string`        | yes      | Dotted namespace (`<domain>.<entity>.<phase>`).                 |                                                 |
| `data`    | `object`        | yes      | Type-specific payload.                                          |                                                 |

**Forward compatibility**: consumers MUST forward unknown `type` values (and unknown fields on `data`) rather than crash. The Pydantic discriminated union (`agloom.protocol.event_adapter`) only recognizes the **v1 catalog** below — UIs that must accept future event types should parse the envelope generically, then dispatch on `type` themselves.

### Capabilities

Canonical **capability tokens** (opaque strings for client routing) live on **`runtime.config`** as `data.capabilities`.

Optionally, **`session.opened`** / **`session.resumed`** may include `data.capabilities_override` (array). When present, clients SHOULD treat it as **session-level hints that override or augment** `runtime.config.capabilities` for that boundary (product-defined merge rule). The reference runtime omits `capabilities_override` and emits an empty `runtime.config.capabilities` unless the embedder configures the emitter’s internal capability list.

---

## Event types (v1 catalog)

Implemented in `agloom.protocol.events` — session lifecycle, execution graph, classification, reasoning, tokens, messages, tools, HITL, workers, memory, checkpoints, feedback, metrics, and errors.

### `session.opened`

Emitted once at the start of every **new** session.

```jsonc
{ "type": "session.opened",
  "data": {
    "runtime_version": "0.1.0",
    "protocol_version": "1"
  } }
```

### `runtime.ready`

Emitted once per runtime attachment after workspace/bootstrap checks and **before** the first `command.invoke`. Carries control-plane hints so clients can render capability badges before the agent graph is fully warm.

```jsonc
{ "type": "runtime.ready",
  "data": {
    "agent_name": "default",
    "cli_tools_enabled": true,
    "cli_tools_count": 25,
    "harness_enabled": false,
    "session_memory_mode": "sqlite",
    "agent_store_kind": "sqlite",
    "mcp_servers_configured": ["filesystem"]
  } }
```

`session_memory_mode` is `sqlite` | `in-memory` | `none` (ephemeral in-process session memory when omitted on the CLI). `mcp_servers_configured` lists names from argv/YAML — servers connect lazily on first invoke.

### `runtime.config`

Emitted in the same startup bundle as `runtime.ready` (immediately after). Carries **`model_id`**, **`tool_names`**, and canonical **`capabilities`** (see **Capabilities** above). May repeat **`cli_tools_enabled`** / **`cli_tools_count`** when CLI tools are on.

```jsonc
{ "type": "runtime.config",
  "data": {
    "model_id": "gpt-4.1",
    "tool_names": [],
    "capabilities": []
  } }
```

### `session.resumed`

Emitted instead of `session.opened` when a client **reconnects** to an existing session (e.g. via `command.session.resume` or when the runtime detects a LangGraph checkpoint for the given thread). `resumed_from_thread` is the thread the client was previously on. `replayed_from_seq` is the first sequence number replayed from the `EventStore` (absent when no replay is performed).

```jsonc
{ "type": "session.resumed",
  "data": {
    "runtime_version": "0.1.0",
    "protocol_version": "1",
    "resumed_from_thread": "thread_abc",
    "replayed_from_seq": 5
  } }
```

### `graph.node.enter` / `graph.node.exit`

Execution DAG events emitted at the boundary of every major execution node — including the `classify` phase and each of the 9 pattern nodes (REACT, SUPERVISOR, SWARM, etc.). Frontends use these to render a live execution graph.

`parent` on `graph.node.exit` SHOULD point at the matching `graph.node.enter.id` for latency attribution.

```jsonc
{ "type": "graph.node.enter",
  "data": {
    "node": "classify",
    "pattern": null,
    "input_preview": "Read pyproject.toml"
  } }

{ "type": "graph.node.exit",
  "parent": "evt_enter_id",
  "data": {
    "node": "classify",
    "duration_ms": 87,
    "output_preview": "pattern=REACT complexity=4",
    "error": null
  } }
```

### `orchestration.step`

Emitted when **recursive orchestration** is enabled (`max_pattern_depth > 0`). One event per orchestration trace step: pattern enter, escalate, or complete. Frontends may show `confidence` / `quality_score` as `conf=XX%` on the CLI.

Only emitted when orchestration runs; omitted for legacy single-pass agents (`max_pattern_depth=0`).

```jsonc
{ "type": "orchestration.step",
  "data": {
    "depth": 1,
    "pattern": "REFLECTION",
    "action": "enter",
    "worker_id": "root",
    "reason": "react_failure_recovery",
    "input_preview": "search arxiv",
    "output_preview": null,
    "duration_ms": null,
    "error": null,
    "confidence": 0.82,
    "quality_score": 0.79
  } }
```

`action` is typically `enter`, `escalate`, or `complete`. See [Recursive orchestration](../features/orchestration.md).

### `pattern.classified`

Emitted by the agloom classifier after `analyze_query`. Tells the UI which of the 9 patterns will execute (REACT, SUPERVISOR, etc.).

```jsonc
{ "type": "pattern.classified",
  "data": { "pattern": "REACT", "complexity": 5, "confidence": 0.9, "reason": "single-tool query" } }
```

### `thinking.step`

A single line in the reasoning trace. `elapsed_ms` lets UIs display per-step timing.

```jsonc
{ "type": "thinking.step",
  "data": { "step": "analyze_query", "label": "Running classifier", "elapsed_ms": 120 } }
```

### `token.delta`

Streaming token from the assistant (or a tool, when role=tool). Whitespace MUST be preserved by both emitter and consumer.

```jsonc
{ "type": "token.delta",
  "data": { "text": "Hello, ", "role": "assistant", "message_id": "m1" } }
```

### `message.user`

Emitted once per `command.invoke`, immediately after `session.opened`, recording the prompt that triggered the turn. Replay tools rebuild the conversation from this + `message.assistant`. The bridge then emits **`prompt.requested`** so observability layers see an explicit “turn accepted” boundary before streaming starts.

```jsonc
{ "type": "message.user",
  "data": { "content": "Read pyproject.toml", "message_id": "u1" } }
```

### `prompt.requested`

Emitted once per invocation immediately after `message.user`. Marks that the runtime will stream agent work for this thread (`kind` is currently always `user_turn`). `preview` is a truncated copy of the user text for dashboards.

```jsonc
{ "type": "prompt.requested",
  "data": { "kind": "user_turn", "preview": "Read pyproject.toml" } }
```

### `prompt.cancelled`

Emitted when an invocation ends early before a normal assistant completion — immediately before the matching `session.closed` on that invocation’s emitter.

| `reason`       | When                                                                                                                                    |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `user_aborted` | `command.cancel` (or targeted cancellation) — user stopped the turn. `detail` is typically `invocation_cancelled`.                      |
| `shutdown`     | Process/WebSocket teardown or `command.runtime.shutdown` — runtime cancelled in-flight tasks. `detail` is typically `runtime_shutdown`. |

```jsonc
{ "type": "prompt.cancelled",
  "data": { "reason": "user_aborted", "detail": "invocation_cancelled" } }

{ "type": "prompt.cancelled",
  "data": { "reason": "shutdown", "detail": "runtime_shutdown" } }
```

### `message.assistant`

Final assistant message for a turn. Carries the same content the UI just streamed (so consumers that ignore `token.delta` still get a complete message).

```jsonc
{ "type": "message.assistant",
  "data": { "content": "Hello, world!", "message_id": "m1", "pattern": "REACT" } }
```

### `skill.loaded`

Emitted when the agent successfully loads a skill body via the `load_skill` tool (after `tool.call.result` for that tool).

```jsonc
{ "type": "skill.loaded",
  "data": { "skill_name": "lint_python", "source": "tool", "body_chars": 2048 } }
```

### `skill.applied`

Emitted when skill-related context is injected into the classifier turn (non-empty skill/delegation catalogue before `analyze_query`).

```jsonc
{ "type": "skill.applied",
  "data": { "phase": "classifier", "injected_chars": 420 } }
```

### `skill.learned`

Emitted when a new skill is persisted: auto-seed bootstrap, on-demand generation after a successful run, or post-run `SkillLearner` extraction.

```jsonc
{ "type": "skill.learned",
  "data": { "skill_name": "deploy_checklist", "pattern": "react", "scope": "global", "source": "post_run" } }
```

### `tool.call.start`

Agent decided to call a tool. Pre-execution; the matching `tool.call.result` or `tool.call.error` follows once the tool returns. Result events SHOULD set `parent` to the start event's `id` so consumers can correlate.

```jsonc
{ "type": "tool.call.start",
  "data": {
    "tool": "read_file",
    "tool_call_id": "tc_42",
    "args": { "path": "pyproject.toml" },
    "worker": "researcher"
  } }
```

### `tool.call.result`

Tool succeeded. `output_preview` is truncated to 1024 chars on the wire; `output_bytes` carries the original size; `truncated=true` signals more data exists.

```jsonc
{ "type": "tool.call.result",
  "parent": "evt_start_id",
  "data": {
    "tool": "read_file",
    "tool_call_id": "tc_42",
    "output_preview": "[project]\nname = \"agloom\"...",
    "output_bytes": 4218,
    "duration_ms": 12,
    "truncated": true
  } }
```

### `tool.call.error`

Tool raised. Distinct from `tool.call.result` so subscribers can render failures without parsing.

```jsonc
{ "type": "tool.call.error",
  "parent": "evt_start_id",
  "data": {
    "tool": "run_shell",
    "tool_call_id": "tc_x",
    "error": "permission denied",
    "error_class": "PermissionError",
    "duration_ms": 4
  } }
```

### `hitl.request`

Runtime asks the user to gate something. The frontend MUST reply with `command.hitl.respond` carrying the same `request_id`; the runtime blocks the agent (via the `user_callback` future registry in `HITLBridge` — see `agloom/runtime/hitl.py`) until the response arrives.

`kind` is one of:

| `kind`             | Options                           | Response                      |
| ------------------ | --------------------------------- | ----------------------------- |
| `tool_approval`    | `accept` / `reject` / `allowlist` | discrete                      |
| `pattern_approval` | `accept` / `reject` / `allowlist` | discrete                      |
| `worker_approval`  | `accept` / `reject` / `allowlist` | discrete                      |
| `react_recovery`   | `retry` / `stop`                  | discrete (no allowlist scope) |
| `clarification`    | (none)                            | free text via `text` field    |

```jsonc
{ "type": "hitl.request",
  "data": {
    "request_id": "hr_abc123",
    "kind": "tool_approval",
    "tool": "read_file",
    "tool_call_id": "tc_42",
    "args": { "path": "pyproject.toml" },
    "options": ["accept", "reject", "allowlist"],
    "default": "reject",
    "agent_name": "agloom-runtime",
    "detail": "Tool: read_file\nArgs: {path: pyproject.toml}"
  } }
```

### `hitl.granted` / `hitl.denied` / `hitl.allowlisted`

Runtime emits the outcome **after** `command.hitl.respond` is received and applied. `parent` SHOULD point at the matching `hitl.request.id`. `decision` carries the discrete token (`accept`/`reject`/`allowlist`/`retry`/`stop`/`timeout`/`cancelled`); for `clarification` kind, `text` carries the user's free-text answer.

```jsonc
{ "type": "hitl.granted",
  "parent": "evt_request_id",
  "data": { "request_id": "hr_abc123", "decision": "accept", "actor": "user" } }
```

### `worker.spawned` / `worker.completed` / `worker.failed` / `worker.halted`

Emitted by SUPERVISOR / SWARM / BLACKBOARD / HYBRID_DAG patterns so frontends can render an agent tree. Result events SHOULD set `parent` to the `worker.spawned.id` for correlation. Nested supervisors set `parent_worker_id` on `worker.spawned`.

`worker.halted` is emitted when a worker stops cooperatively (e.g. user `HALT_ALL`) — **not** a retryable failure. Patterns set `WorkerResult.signal` to `HALTED`; the runtime bridge maps that to `worker.halted` instead of `worker.failed`.

```jsonc
{ "type": "worker.spawned",
  "data": {
    "worker_id": "w_1",
    "name": "researcher",
    "pattern": "SUPERVISOR",
    "task": "gather facts about Q3 sales",
    "parent_worker_id": null
  } }

{ "type": "worker.completed",
  "parent": "evt_spawn_id",
  "data": { "worker_id": "w_1", "output_preview": "…", "output_bytes": 4218, "duration_ms": 2400, "truncated": true } }

{ "type": "worker.failed",
  "parent": "evt_spawn_id",
  "data": { "worker_id": "w_1", "error": "rate limited", "error_class": "RateLimitError", "duration_ms": 1500 } }

{ "type": "worker.halted",
  "parent": "evt_spawn_id",
  "data": { "worker_id": "w_1", "reason": "HALT_ALL", "output_preview": "Stopped by user.", "duration_ms": 800 } }
```

### `metric.tokens` / `metric.cost`

Per-LLM-call **delta** updates. Frontends sum across the session for the sidebar's "≈ est. tokens" / "≈ cost" rollup. `phase` distinguishes classifier / react / reflection / synthesizer billing; `worker_id` is set when the metric belongs to a specific worker (SUPERVISOR / SWARM).

```jsonc
{ "type": "metric.tokens",
  "data": {
    "model": "groq:llama-3.3-70b",
    "input_tokens": 200,
    "output_tokens": 80,
    "total_tokens": 280,
    "phase": "react",
    "worker_id": null
  } }

{ "type": "metric.cost",
  "data": {
    "cost": 0.0042,
    "currency": "USD",
    "model": "groq:llama-3.3-70b",
    "phase": "react",
    "estimated": true
  } }
```

Set **`estimated": true`** when the runtime computed an approximate cost (provider omitted dollar metadata). Clients should label rollups as approximate.

### `memory.session.write`

Emitted after each turn is persisted into session (short-term) memory.

```jsonc
{ "type": "memory.session.write",
  "data": {
    "thread": "thread_xyz",
    "run_id": "run_abc",
    "query_preview": "Read pyproject.toml",
    "output_preview": "The file contains...",
    "turn_count": 3
  } }
```

### `memory.session.turn_popped`

Emitted after **`command.memory.pop_last_turn`** removes the most recent turn from session memory (e.g. CLI **`/undo`**).

```jsonc
{ "type": "memory.session.turn_popped",
  "data": { "thread": "thread_xyz", "remaining_turns": 2 } }
```

### `memory.lt.recall`

Emitted when long-term memory is searched to inject context before classification.

```jsonc
{ "type": "memory.lt.recall",
  "data": {
    "namespace": "user/default",
    "query_preview": "Read pyproject.toml",
    "hits": 2,
    "injected_chars": 380
  } }
```

### `memory.lt.store`

Emitted when the `save_memory` tool writes a fact to long-term storage.

```jsonc
{ "type": "memory.lt.store",
  "data": { "namespace": "user/default", "key": "project_goal", "content_preview": "Build a..." } }
```

### `checkpoint.saved`

Emitted after the agent successfully persists a LangGraph checkpoint (typically after each completed turn). Payload includes query, output, steps, and classifier **`analysis`** when available — so **`resume()`** can continue an interrupted run without re-classifying.

```jsonc
{ "type": "checkpoint.saved",
  "data": { "thread": "thread_xyz", "run_id": "run_abc", "label": null } }
```

### `checkpoint.restored`

Emitted when the runtime detects and resumes from an existing checkpoint.

```jsonc
{ "type": "checkpoint.restored",
  "data": { "thread": "thread_xyz", "resumed_from_run_id": "run_prev" } }
```

### `feedback.scored`

Emitted after a `command.feedback` is received and processed.

```jsonc
{ "type": "feedback.scored",
  "data": {
    "run_id": "run_abc",
    "rating": "positive",
    "comment": "Great answer!",
    "correct": ""
  } }
```

### `error.fatal` / `error.transient`

Fatal errors precede a `session.closed(reason="error")`. Transient errors (rate-limit backoff, retry-recoverable provider hiccups) do not end the session. `stage` names the runtime phase (`"classify"`, `"react"`, `"tool"`, `"stream"`, `"invocation"`).

```jsonc
{ "type": "error.fatal",
  "data": {
    "severity": "fatal",
    "message": "provider rejected the model output",
    "error_class": "RuntimeError",
    "stage": "invocation",
    "retryable": false
  } }
```

### `session.closed`

Emitted exactly once at the end. `reason` is `completed | user_aborted | error | shutdown`.

```jsonc
{ "type": "session.closed",
  "data": { "reason": "completed", "duration_ms": 1234 } }
```

---

## Versioning & namespace reservation

Already shipped (**v1**): `session.*`, `runtime.*`, `graph.*`, `pattern.*`, `thinking.*`, `token.*`, `message.*`, **`prompt.*`**, **`skill.*`**, `tool.*`, `hitl.*`, `worker.*`, `memory.*`, `checkpoint.*`, `feedback.*`, `metric.*`, `error.*`.

Additional event types may appear under existing namespaces without bumping **`v`** — follow the same dotted `type` convention and additive payload rules. Names not listed above remain available for new envelopes under those namespaces.

### Machine-readable schemas

`python -m agloom.protocol.schema --out agp-schema.json` exports **events** (`oneOf` at the root) plus an auxiliary **`agp_commands`** object describing inbound **`command.*`** payloads (merged into the same file’s `$defs`). Maintainers: see [AGP from Python](../guides/agp-python.md) for contract-test layout.

---

<a id="agp-inbound-commands"></a>

## Inbound commands (frontend → runtime)

Commands share the envelope format. The runtime serve loop reads NDJSON from stdin concurrently with the running invocation, so commands and events interleave.

### `command.invoke`

Start a new turn. Multiple invocations on different `thread` ids may run concurrently.

```jsonc
{ "type": "command.invoke",
  "data": { "prompt": "Read pyproject.toml", "thread": "thread_xyz" } }
```

### `command.hitl.respond`

Resolve a pending `hitl.request`. The runtime blocks the agent's `user_callback` until the matching response arrives. Garbled / unknown `decision` tokens normalize to `reject` (never auto-approve on bad input).

```jsonc
{ "type": "command.hitl.respond",
  "data": {
    "request_id": "hr_abc123",
    "decision": "accept",
    "text": "<free text — only for clarification kind>"
  } }
```

### `command.cancel`

Cancel one in-flight invocation (or all, if `thread` is omitted). The bridge translates the resulting `CancelledError` into `session.closed(reason="user_aborted")` so frontends see a clean boundary rather than an error pane.

```jsonc
{ "type": "command.cancel",
  "data": { "thread": "thread_xyz" } }
```

Any HITL gates the cancelled invocation was awaiting are automatically resolved as `cancelled` so they don't hang indefinitely.

### `command.feedback`

Submit user feedback for a completed turn. The runtime calls the agent's `feedback_handler` (if configured) and always emits a `feedback.scored` event on the wire.

`run_id` comes from `message.assistant.data.run_id` so the frontend can correlate ratings with turns.

```jsonc
{ "type": "command.feedback",
  "data": {
    "run_id": "run_abc123",
    "rating": "positive",
    "comment": "Very helpful!",
    "correct": ""
  } }
```

### `command.worker.assign`

Dispatch a task to a named worker. The runtime starts an in-process worker task and streams lifecycle events; routing to remote nodes would use the same command shape as an optional future extension. The supervisor sees a `worker.spawned` event immediately, then `worker.completed`, `worker.halted`, or `worker.failed` when the task ends.

`parent_thread` correlates the worker's events to the originating supervisor invocation.

```jsonc
{ "type": "command.worker.assign",
  "data": {
    "worker_id": "w_1",
    "task": "Summarise the error logs for the last hour",
    "thread": "wt_abc",
    "parent_thread": "thread_xyz",
    "pattern": "REACT",
    "tools": ["read_file", "grep_files"]
  } }
```

### `command.session.resume`

Reconnect to an existing **AGP session** and replay buffered envelopes. The runtime emits `session.resumed` and, when an `EventStore` is configured, replays all events with `seq >= from_seq` so the client catches up. This is **not** the same as **`agent.resume()`** in the Python library (graph interrupt continuation after HITL).

```jsonc
{ "type": "command.session.resume",
  "data": { "thread": "thread_xyz", "from_seq": 5 } }
```

### `command.snapshot.request`

Request a **manual LangGraph checkpoint**; the runtime emits `checkpoint.saved` when it succeeds. The agent must have been created with a **`checkpointer`** — otherwise the runtime logs to stderr and skips emission.

```jsonc
{ "type": "command.snapshot.request",
  "data": { "thread": "thread_xyz", "label": "manual-save" } }
```

`thread` and `label` are optional (`label` is stored as checkpoint metadata when supported).

### `command.memory.pop_last_turn`

Remove the **most recent** session-memory turn for a thread (does not rewind LangGraph checkpoints). The runtime emits **`memory.session.turn_popped`** with **`remaining_turns`**, or **`error.transient`** when the thread is empty or memory is disabled.

```jsonc
{ "type": "command.memory.pop_last_turn",
  "data": { "thread": "thread_xyz" } }
```

`thread` is optional — when omitted, the runtime uses the active invocation thread.

### `command.runtime.shutdown`

Graceful exit. Cancels in-flight invocations, resolves outstanding HITL gates as `cancelled`, emits `session.closed(reason="shutdown")`, and exits.

```jsonc
{ "type": "command.runtime.shutdown" }
```

---

## EventStore (replay / resume)

The `EventStore` is an append-only, session-scoped event log wired into every `SessionEmitter` (via the `store=` param). It enables:

- **Replay on reconnect**: the serve loop reads buffered events and re-streams them after `session.resumed`.
- **Offline audit**: SQLite backend persists the full event trace to disk.

Two concrete implementations:

| Class              | Persistence | Use case                                  |
| ------------------ | ----------- | ----------------------------------------- |
| `MemoryEventStore` | in-process  | tests, single-process deploys             |
| `SqliteEventStore` | SQLite file | durable tracing, multi-turn observability |

Wire it in via `--store` flag:

```bash
agloom-runtime serve --transport=stdio --store=sqlite --store-path=agp_events.db
agloom-runtime serve --transport=ws    --store=memory
```

Or programmatically:

```python
from agloom.protocol import SessionEmitter
from agloom.protocol.store import SqliteEventStore

store = SqliteEventStore("agp_events.db")
em = SessionEmitter(session="s_1", thread="t_1", store=store)
```

---

## WebSocket transport

```bash
agloom-runtime serve --transport=ws --host 0.0.0.0 --port 8765
# requires: pip install 'agloom[ws]'  (installs websockets>=12.0)
```

Each connecting client gets its own AGP session. The same inbound NDJSON command format applies over WebSocket frames (one JSON per frame, no line terminator required — but NDJSON with `\n` is also accepted). Outbound events stream as one JSON line per frame.

---

## Python API reference (emitters, stores, runtime)

Pointers to the code that implements AGP on the Python side (this is **not** a second list of inbound commands; see [Inbound commands (frontend → runtime)](#agp-inbound-commands) above for `command.*` shapes).

- Python emitter: `agloom.protocol.SessionEmitter` (`agloom/protocol/emitter.py`)
- Async emitter: `agloom.protocol.AsyncSessionEmitter` (WebSocket / non-blocking)
- Pydantic event models: `agloom.protocol.events` (`agloom/protocol/events.py`)
- Pydantic command models: `agloom.protocol.commands` (`agloom/protocol/commands.py`)
- EventStore: `agloom.protocol.store` (`agloom/protocol/store.py`) — `MemoryEventStore`, `SqliteEventStore`
- Bridge / translator: `agloom.runtime` (`agloom/runtime/__init__.py`)
- Stdio entry point: `agloom-runtime serve --transport=stdio` (also `python -m agloom.runtime serve`)
- WebSocket entry point: `agloom-runtime serve --transport=ws [--host …] [--port …]`

```python
# Programmatic emit
from agloom.protocol import SessionEmitter

em = SessionEmitter(session="sess_a", thread="thread_b")
em.open()
em.emit_pattern_classified(pattern="REACT", complexity=5)
em.emit_thinking_step(step="analyze_query", elapsed_ms=120)
em.emit_token_delta(text="Hello, ")
em.emit_token_delta(text="world!")
em.emit_message_assistant(content="Hello, world!")
em.close(reason="completed", duration_ms=1234)
```

```python
# Programmatic consume
import json
from agloom.protocol import event_adapter

for line in stream:
    raw = json.loads(line)
    evt = event_adapter.validate_python(raw)   # Phase-0 closed-union parse
    # …or for forward-compat: dispatch on raw["type"] yourself.
```
