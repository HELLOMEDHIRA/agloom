# agloom Observability Platform — Architecture

> Stack: FastAPI · SQLite (aiosqlite) · SSE · AGP event sourcing · React · recharts · React Flow

---

## 1. Design Philosophy

Every AGP event that the Python runtime emits is a first-class trace event.  
The observability platform is not a bolt-on monitoring layer — it is the **natural consequence of AGP being an event-sourced protocol**.

```text
agloom-core / agloom-runtime
       │  emits AGP Envelopes
       ▼
 ObservabilityStore (SQLite)    ◀── append every Envelope at ingest time
       │
       ├─ REST API  /sessions, /sessions/:id/events, /sessions/:id/metrics
       ├─ SSE stream  /live                          ← realtime dashboard feed
       └─ Replay API  /sessions/:id/replay           ← re-emit stored events
              │
              ▼
  agloom_web  /observe  (dashboard)
  agloom_web  /observe/session/:id  (trace viewer)
```

The default stack uses SQLite only. Heavier analytics backends can be layered on later without changing the AGP contract.

---

## 2. Observability Platform Components

### 2.1 Python observability module

Public API (import from **`agloom.observability`**):

| Component | Role |
| ----------- | ---- |
| **ObservabilityStore** | Append AGP envelopes; query by session |
| **MetricsAggregator** | Per-session token / turn aggregates |
| **ReplayEngine** | Re-emit stored events (real-time or accelerated) |
| **HTTP router** | FastAPI routes mounted when `agloom-runtime serve --obs` |

Default backing store is **SQLite** (async via aiosqlite). Swap implementations only if you need shared analytics storage — the AGP event shape stays the same.

### 2.2 Storage schema (SQLite)

```sql
-- One row per AGP Envelope
CREATE TABLE events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    thread_id  TEXT,
    run_id     TEXT,
    seq        INTEGER NOT NULL,
    event_type TEXT    NOT NULL,
    ts         TEXT    NOT NULL,    -- ISO-8601 from Envelope.ts
    payload    TEXT    NOT NULL,    -- Full JSON Envelope
    created_at INTEGER NOT NULL     -- UNIX ms (for range queries)
);
CREATE INDEX idx_session ON events(session_id, seq);
CREATE INDEX idx_type    ON events(event_type);
CREATE INDEX idx_ts      ON events(created_at);

-- Materialized session summary (updated on session.closed)
CREATE TABLE sessions (
    session_id    TEXT PRIMARY KEY,
    thread_id     TEXT,
    started_at    TEXT NOT NULL,
    ended_at      TEXT,
    status        TEXT NOT NULL DEFAULT 'open',   -- open|closed|error
    pattern       TEXT,
    total_turns   INTEGER NOT NULL DEFAULT 0,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    duration_ms   INTEGER
);
```

### 2.3 Metrics model

Derived on-demand from the `events` table — no separate write path needed.

| Metric               | Derived from                                            | Unit  |
| -------------------- | ------------------------------------------------------- | ----- |
| `input_tokens`       | `metric.tokens` events                                  | count |
| `output_tokens`      | `metric.tokens` events                                  | count |
| `llm_latency_ms`     | `thinking.step` with `elapsed_ms` where step='llm_call' | ms    |
| `tool_duration_ms`   | `tool.result` with `duration_ms`                        | ms    |
| `worker_duration_ms` | `worker.completed` with `duration_ms`                   | ms    |
| `node_duration_ms`   | `graph.node.exit` with `duration_ms`                    | ms    |
| `hitl_gates`         | `hitl.request` event count                              | count |
| `retries`            | `error.transient` event count                           | count |
| `turn_count`         | `message.user` event count                              | count |

### 2.4 Replay Architecture

```text
ReplayEngine.replay(session_id, speed=1.0)
    │
    ├── load events from ObservabilityStore (ordered by seq)
    ├── for each consecutive pair: compute Δt from ts field
    ├── sleep(Δt / speed)   ← speed=0 means instant replay
    └── yield Envelope      ← caller writes to SSE / WebSocket
```

Replay streams through the same SSE endpoint as live execution.  
The frontend cannot distinguish replay from live — ensuring UX parity.

---

## 3. API Surface

### REST endpoints

```text
GET  /observe/sessions                           → SessionSummary[]
GET  /observe/sessions/:session_id               → SessionDetail (summary + first 50 events)
GET  /observe/sessions/:session_id/events        → AGP Envelope[]  (paginated, filterable)
GET  /observe/sessions/:session_id/metrics       → SessionMetrics
GET  /observe/sessions/:session_id/graph         → GraphTrace (node enter/exit pairs)
GET  /observe/sessions/:session_id/workers       → WorkerTrace[]
DELETE /observe/sessions/:session_id             → 204 (purge)
```

### SSE / streaming endpoints

```text
GET  /observe/live                               → SSE stream of all live AGP events
GET  /observe/sessions/:session_id/replay        → SSE stream of stored events
     ?speed=1.0                                    (1.0=real-time, 2.0=2x, 0=instant)
```

### Ingest endpoint (internal — called by RuntimeNode)

```text
POST /observe/ingest                             → accepts a single AGP Envelope
```

In practice the `ObservabilityStore` is injected directly into the `RuntimeNode`  
and envelopes are appended in-process — no separate HTTP ingest endpoint is required.

---

## 4. Frontend Observability Routes

Added to `agloom_web`:

```text
/observe                                → ObservabilityDashboard (session list + global metrics)
/observe/session/:sessionId             → SessionTrace (full trace viewer)
  ├── TraceTimeline                     — horizontal swim-lane timeline
  ├── GraphTracer                       — React Flow replay of LangGraph execution
  ├── MetricsPanel                      — recharts token/latency/throughput charts
  ├── ReplayPlayer                      — SSE replay with speed control
  └── WorkerMonitor                     — worker health + task history
```

---

## 5. Observability Event Categories

All AGP event types contribute to observability. Priority groupings:

### Tier 1 — Core Execution Trace

`message.user`, `message.assistant`, `pattern.classified`, `thinking.step`, `tool.call`, `tool.result`

### Tier 2 — Orchestration Visibility

`graph.node.enter`, `graph.node.exit`, `worker.spawned`, `worker.completed`, `worker.failed`

### Tier 3 — Runtime State

`checkpoint.saved`, `checkpoint.restored`, `session.opened`, `session.closed`, `session.resumed`

### Tier 4 — Performance Metrics

`metric.tokens`, `hitl.request`, `hitl.decided`, `error.transient`, `error.fatal`

---

## 6. Distributed Tracing Compatibility

AGP envelopes already carry `session`, `thread`, `run_id` — sufficient for correlation.

Future extension: emit AGP events with W3C TraceContext headers:

```python
# Envelope extension (additive, non-breaking)
trace_id: Optional[str]   # W3C trace-id (128-bit hex)
span_id:  Optional[str]   # W3C parent-id (64-bit hex)
```

This maps directly to OpenTelemetry spans:

- `session` → root span
- `thread` → sub-span per conversation turn
- `graph.node.enter/exit` → child spans per LangGraph node
- `tool.call/result` → leaf spans per tool execution

---

## 7. Scaling & backends

Today the observability store is **SQLite** suitable for single-process and local deployments. Larger deployments may swap in PostgreSQL, columnar warehouses, or OTLP export while keeping the same REST/SSE API shapes.

---

## 8. Runtime integration

Enable observability when starting the bridge:

```bash
agloom-runtime serve --obs --obs-db ./obs.sqlite --obs-port 8766
```

Custom embedders can attach an **`ObservabilityStore`** to **`RuntimeNode.create_local(...)`** — envelopes are ingested in-process after each emit. See [Observability API (Python)](../guides/observability-python.md).

---

## 9. Security Considerations

- The observability API is **read-only** by default
- Ingest is in-process only (no unauthenticated HTTP ingest endpoint exposed)
- Replay streams require `session_id` — treat open deployments like internal dashboards until auth is configured.

Future hardening may add JWT-gated APIs and row-level session ownership.

---

## 10. Developer Debugging Workflow

```text
1. Agent run fails
2. Open /observe/session/:id
3. TraceTimeline shows exactly where execution diverged
4. GraphTracer shows which LangGraph node was active
5. Click on a worker.failed event → see full error + stack trace
6. Click Replay → re-run session events to reproduce the state
7. Checkpoint inspector shows the LangGraph state snapshot at any point
```

This is the AI-native equivalent of a distributed tracing waterfall (Jaeger, Zipkin) — but the events are LangGraph nodes and AGP workers, not HTTP requests.
