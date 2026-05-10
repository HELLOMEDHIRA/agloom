# Agloom Protocol (AGP) — v1

**Status:** stable (v1). AGP is emitted by **`agloom-runtime serve`** (stdio or WebSocket); **agloom CLI**, web workspace, and other clients consume the same event stream.

AGP is a UI-agnostic, transport-agnostic, event-driven contract between the Python runtime and any frontend. This page is the wire-format reference; see **`agloom/docs/runtime/architecture.md`** for runtime layout.

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

| Field      | Type             | Required | Notes                                                                   |
| ---------- | ---------------- | -------- | ----------------------------------------------------------------------- |
| `v`        | `"1"`            | yes      | Major protocol version. Bumped only on breaking schema changes.          |
| `id`       | `string`         | yes      | Opaque, time-ordered-ish unique id (currently `evt_<24 hex>`).           |
| `ts`       | ISO-8601 string  | yes      | Aware UTC timestamp.                                                    |
| `session`  | `string`         | yes      | Session id; stable across reconnects.                                   |
| `thread`   | `string`         | yes      | LangGraph thread id (resume key).                                       |
| `seq`      | `int >= 0`       | yes      | Monotonic per session — gap detection.                                  |
| `parent`   | `string \| null` | no       | Causal parent event id.                                                 |
| `trace`    | `string \| null` | no       | OpenTelemetry trace id when tracing is enabled.                         |
| `type`     | `string`         | yes      | Dotted namespace (`<domain>.<entity>.<phase>`).                          |
| `data`     | `object`         | yes      | Type-specific payload.                                                  |

**Forward compatibility**: consumers MUST forward unknown `type` values (and unknown fields on `data`) rather than crash. The Pydantic discriminated union (`agloom.protocol.event_adapter`) is closed over Phase-0 types — UIs that need forward-compat parse the envelope first, then dispatch on `type` themselves.

---

## Phase 0 / 0.7 events (this release)

All shipped in `agloom.protocol`. Event types covering session lifecycle, execution graph, classification, reasoning, tokens, messages, tool execution, HITL, worker tree, metrics, and errors.

### `session.opened`

Emitted once at the start of every **new** session.

```jsonc
{ "type": "session.opened",
  "data": {
    "runtime_version": "0.1.0",
    "protocol_version": "1",
    "capabilities": ["agp.v1.minimal"]
  } }
```

### `session.resumed`

Emitted instead of `session.opened` when a client **reconnects** to an existing session (e.g. via `command.session.resume` or when the runtime detects a LangGraph checkpoint for the given thread). `resumed_from_thread` is the thread the client was previously on. `replayed_from_seq` is the first sequence number replayed from the `EventStore` (absent when no replay is performed).

```jsonc
{ "type": "session.resumed",
  "data": {
    "runtime_version": "0.1.0",
    "protocol_version": "1",
    "capabilities": ["agp.v1.minimal"],
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

Emitted once per `command.invoke`, immediately after `session.opened`, recording the prompt that triggered the turn. Replay tools rebuild the conversation from this + `message.assistant`.

```jsonc
{ "type": "message.user",
  "data": { "content": "Read pyproject.toml", "message_id": "u1" } }
```

### `message.assistant`

Final assistant message for a turn. Carries the same content the UI just streamed (so consumers that ignore `token.delta` still get a complete message).

```jsonc
{ "type": "message.assistant",
  "data": { "content": "Hello, world!", "message_id": "m1", "pattern": "REACT" } }
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

| `kind`              | Options                            | Response                       |
| ------------------- | ---------------------------------- | ------------------------------ |
| `tool_approval`     | `accept` / `reject` / `allowlist`  | discrete                       |
| `pattern_approval`  | `accept` / `reject` / `allowlist`  | discrete                       |
| `worker_approval`   | `accept` / `reject` / `allowlist`  | discrete                       |
| `react_recovery`    | `retry` / `stop`                   | discrete (no allowlist scope)  |
| `clarification`     | (none)                             | free text via `text` field     |

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

### `worker.spawned` / `worker.completed` / `worker.failed`

Emitted by SUPERVISOR / SWARM / BLACKBOARD / HYBRID_DAG patterns so frontends can render an agent tree. Result events SHOULD set `parent` to the `worker.spawned.id` for correlation. Nested supervisors set `parent_worker_id` on `worker.spawned`.

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
  "data": { "cost": 0.0042, "currency": "USD", "model": "groq:llama-3.3-70b", "phase": "react" } }
```

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

Emitted after `_save_checkpoint` successfully persists a LangGraph checkpoint.

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

## Roadmap (additive — no schema bumps required)

These domains are reserved for future phases:

| Domain         | Examples                                                        |
| -------------- | --------------------------------------------------------------- |
| `skill.*`      | `skill.loaded`, `skill.applied`, `skill.learned`                |
| `prompt.*`     | `prompt.requested`, `prompt.cancelled`                          |

Already shipped (v1): `session.*`, `graph.*`, `pattern.*`, `thinking.*`, `token.*`, `message.*`, `tool.*`, `hitl.*`, `worker.*`, `memory.*`, `checkpoint.*`, `feedback.*`, `metric.*`, `error.*`.

---

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

Dispatch a task to a named worker. In Phase 1 (single-process) the runtime spawns an in-process agent task; in Phase 2 (distributed) this routes to a remote worker node via a message broker. The supervisor sees a `worker.spawned` event immediately, then `worker.completed` or `worker.failed` when the task ends.

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

Reconnect to an existing session. The runtime emits `session.resumed` and, when an `EventStore` is configured, replays all events with `seq >= from_seq` so the client catches up.

```jsonc
{ "type": "command.session.resume",
  "data": { "thread": "thread_xyz", "from_seq": 5 } }
```

### `command.runtime.shutdown`

Graceful exit. Cancels in-flight invocations, resolves outstanding HITL gates as `cancelled`, emits `session.closed(reason="shutdown")`, and exits.

```jsonc
{ "type": "command.runtime.shutdown" }
```

Future commands (Phase 1+): `command.snapshot.request` (manual snapshots without a pending turn).

---

## EventStore (replay / resume)

The `EventStore` is an append-only, session-scoped event log wired into every `SessionEmitter` (via the `store=` param). It enables:

- **Replay on reconnect**: the serve loop reads buffered events and re-streams them after `session.resumed`.
- **Offline audit**: SQLite backend persists the full event trace to disk.

Two concrete implementations:

| Class             | Persistence | Use case                                  |
| ----------------- | ----------- | ----------------------------------------- |
| `MemoryEventStore`| in-process  | tests, single-process deploys             |
| `SqliteEventStore`| SQLite file | durable tracing, multi-turn observability |

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

## Inbound commands (frontend → runtime)

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
