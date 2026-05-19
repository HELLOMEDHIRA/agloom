# agloom-runtime Architecture

**Audience:** operators and integrators running **`agloom-runtime serve`** or building custom AGP transports.  
If you only embed `create_agent` in Python, start with [Integration overview](../guides/developer-overview.md) instead.

**Status**: Stable (foundations shipped) | **AGP protocol**: v1 | **Package**: [PyPI `agloom`](https://pypi.org/project/agloom/)  
**Last updated**: May 2026

---

## 1. Vision

`agloom-runtime` evolves agloom from a local Python agent framework into a
**distributed AI-native execution platform**. Its single design principle:

> *agloom-core owns* **what** *to execute; agloom-runtime owns* **where, when, and how** *to execute it.*

AGP (Agloom Protocol) is the communication backbone across every boundary —
local ↔ remote workers, runtime ↔ frontend, runtime ↔ observability, runtime ↔ cloud.

---

## 2. Responsibility Split

| Concern                     | agloom-core                   | agloom-runtime       |
| --------------------------- | ----------------------------- | -------------------- |
| Orchestration semantics     | ✅ LangGraph graphs           | ❌                   |
| Memory / knowledge          | ✅ LTM, episodic, session     | ❌                   |
| Tools / MCP                 | ✅ tool definitions, adapters | ❌                   |
| Agent logic / patterns      | ✅ REACT, SUPERVISOR, etc.    | ❌                   |
| LangGraph checkpoints       | ✅ saves/restores             | runtime triggers     |
| **Worker lifecycle**        | ❌                            | ✅                   |
| **Task scheduling**         | ❌                            | ✅                   |
| **Distributed routing**     | ❌                            | ✅                   |
| **Fault tolerance**         | ❌                            | ✅                   |
| **Transport layer**         | ❌                            | ✅ stdio / ws / HTTP |
| **Execution observability** | emits AgentEvents             | ✅ translates → AGP  |

The boundary is clean: the **agent library** produces an internal event stream;
**agloom-runtime** schedules work, maps those events to **AGP envelopes**, and
writes them to your transport (stdio, WebSocket, etc.).

---

## 3. Execution Model — Event-Driven Actor Runtime

**Decision**: Hybrid **Actor Model + Event-Driven Scheduling** (not pure task-queue,
not pure graph executor).

### Why not pure task-queue (Celery / RQ)?

- No per-task streaming; results are point-in-time
- Workers are anonymous processes, not addressable actors
- No built-in AGP event routing

### Why not distributed graph execution (Dask / Prefect)?

- Requires reimplementing what LangGraph already does
- Breaks the core/runtime separation

### Why Actor Model (Erlang / Akka style)?

- Every worker is an **actor** with its own identity (`worker_id`), state, and async inbox
- AGP `command.*` envelopes are actor messages; `event.*` envelopes are actor outputs
- The `session` + `thread` fields on every AGP envelope are already natural actor routing keys
- Fault tolerance is modelled as actor supervision (restart / escalate / abandon)
- Scales additively: local actors → remote actors → cluster actors, same AGP protocol

```text
┌─────────────────────────────────────────────────────────────────┐
│  RuntimeNode                                                    │
│                                                                 │
│  ┌──────────────┐  route  ┌─────────────────────────────────┐  │
│  │  Scheduler   │ ──────► │  WorkerPool                     │  │
│  │  (priority   │         │  ┌─────────┐  ┌─────────────┐  │  │
│  │   queue +    │ ◄─────  │  │AI Worker│  │ Tool Worker │  │  │
│  │  capability  │ health  │  │ (local) │  │  (isolated) │  │  │
│  │  matching)   │         │  └────┬────┘  └──────┬──────┘  │  │
│  └──────────────┘         │       │ AGP events    │         │  │
│         ▲                 └───────┼───────────────┼─────────┘  │
│         │                         │               │            │
│  ┌──────┴──────┐           ┌──────▼───────────────▼──────┐    │
│  │  Registry   │           │  RuntimeEventBus (AGP)       │    │
│  │ (discover   │           │  routes events to sessions   │    │
│  │  workers)   │           └──────────────────────────────┘    │
│  └─────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
             │ AGP (stdio / ws / HTTP)
             ▼
    ┌─────────────────┐
    │ agloom CLI / Web │
    │  Dashboard / VS │
    └─────────────────┘
```

---

## 4. Worker Abstraction Model

Every execution unit is a `BaseWorker`. The protocol is minimal by design:

```python
class BaseWorker(ABC):
    worker_id: str
    worker_type: WorkerType
    capabilities: list[str]        # matched by Scheduler
    max_concurrency: int           # how many tasks simultaneously

    async def start() -> None      # acquire resources
    async def stop() -> None       # release resources, drain in-flight
    async def execute(
        task: WorkerTask,
        emitter: AsyncSessionEmitter,
    ) -> None                      # execute + stream AGP events
    async def health_check() -> WorkerHealth
```

### Worker types (shipped)

| Type            | Description                                          |
| --------------- | ---------------------------------------------------- |
| Local AI worker | Runs `create_agent` invocations in-process, streams progress to AGP |
| `ToolWorker`    | Executes a single tool call in isolation             |

Additional worker kinds (remote brokers, GPU pools, browsers, etc.) are **extension points** for integrators building on the same AGP contracts.

### Worker Capability Tags

Workers declare capabilities as string tags. The scheduler matches tasks to workers:

```text
"agent:react"           "agent:supervisor"     "agent:cot"
"tool:filesystem"       "tool:web_search"      "tool:code_exec"
"inference:gpu"         "inference:cpu"
"embed:dense"           "embed:sparse"
"spark"                 "ray"                  "flink"
"browser"               "network"
```

---

## 5. Scheduling Model

**Current**: Single-node priority queue (asyncio-native, minimal infrastructure)

```text
WorkerTask
  .priority      int   (0 = normal, 1 = high, -1 = background)
  .required_caps list  (e.g. ["agent:react", "tool:filesystem"])
  .timeout_ms    int?  (server-side deadline)
  .retry_policy  RetryPolicy
```

**Scheduling algorithm** (capability-aware FIFO):

1. New task arrives → pushed to `asyncio.PriorityQueue`
2. Dispatcher loop pops next task, finds first idle worker with matching capabilities
3. If no worker available → task waits in queue (bounded wait, configurable)
4. On timeout → emit `error.transient` + retry (if policy allows) or `error.fatal`

Heavier deployments may introduce pluggable schedulers (Redis, brokers) behind the same task API — without changing AGP envelopes.

---

## 6. AGP runtime messaging flow

```text
Client (CLI / web / your service)
  │
  │  command.invoke { prompt, thread, session }
  ▼
Runtime receives command
  │
  ▼
Scheduler queues an agent invocation
  │
  ▼
In-process agent runs (classify → pattern → tools / workers)
  │
  │  Internal progress events
  ▼
Runtime maps each step → AGP envelope
  │
  ▼
NDJSON line or WebSocket frame to client
  │
  ▼
Client renders: pattern.classified, thinking.step, token.delta,
                tool.call.*, message.assistant, session.closed
```

**Worker assignment** for distributed execution uses two new AGP commands:

```json
{"type":"command.worker.assign","data":{"worker_id":"w_gpu_1","task_id":"t_42","payload":{...}}}
{"type":"worker.spawned",       "data":{"worker_id":"w_gpu_1","name":"gpu-inference"}}
{"type":"worker.completed",     "data":{"worker_id":"w_gpu_1","output_preview":"..."}}
```

---

## 7. Remote Worker Communication Strategy

Three patterns deployments may adopt:

### Pattern A — Direct AGP over WebSocket

Remote worker runs `agloom-runtime serve --transport=ws`.
Supervisor runtime connects as a WebSocket client and sends `command.worker.assign`.
Worker streams AGP events back over the same connection.

```text
Supervisor RuntimeNode ──WS──► Remote Worker RuntimeNode
  send: command.worker.assign         recv: worker.spawned
  recv: AGP event stream  ◄───        emit: token.delta, message.assistant, ...
```

### Pattern B — AGP over message broker

Each `RuntimeNode` publishes/subscribes to topics on a broker (NATS / Kafka).
Topic naming: `agp.session.<session_id>.commands` / `agp.session.<session_id>.events`.
Enables fan-out to multiple consumers (dashboards, monitoring, logging).

### Pattern C — Hosted control plane

`agloom-cloud` control plane manages worker registration and assignment.
Workers register capabilities; control plane matches tasks to workers globally.
Heartbeat + capability refresh every 30s.

---

## 8. Checkpoint / Recovery Architecture

LangGraph checkpoints remain inside the Python agent library. Saved state includes classifier output when a turn was classified, so **`agent.resume()`** can continue without re-picking a pattern. The runtime's role is:

1. **Trigger**: `command.snapshot.request` → asks the agent to persist a checkpoint
2. **Observe**: `checkpoint.saved` / `checkpoint.restored` events on the AGP wire
3. **Reconnect**: `command.session.resume {thread, from_seq}` → replay **EventStore** (AGP envelopes) for disconnected clients
4. **Graph resume**: Python callers use **`agent.resume(value, thread_id=…)`** with a checkpointer (separate from step 3 — this is not an AGP command)

```text
                Runtime                              Core
                ───────                              ─────
command.session.resume ──────────────────────►
                        replay EventStore
                        (all events since from_seq)
                                      ──────────────► LangGraph.restore(thread)
                                      ◄──────────────  AgentEvent stream
                        translate → AGP
checkpoint.restored ◄─────────────────────────────────
```

**EventStore backends** (shipped today):

- `MemoryEventStore` — single process, no persistence
- `SqliteEventStore` — single host, survives restarts

Larger deployments may add PostgreSQL or columnar stores behind the same replay semantics.

**LangGraph agent store** (``--agent-store`` on `serve`; not the AGP EventStore):

- Default **`sqlite`** → LangGraph **AsyncSqliteStore** (requires **`aiosqlite`**).
- Missing **`aiosqlite`** or DB open failure → **InMemoryStore**, one **stderr** line, serve continues; no persistence across restarts until fixed (same as ``--agent-store=memory``).

---

## 9. State Synchronisation

Workers share no mutable state. All coordination happens through events:

```text
Worker A emits: worker.completed {worker_id: "w1", output_preview: "..."}
Supervisor receives: → WorkerPool updates worker status in local registry
                    → Scheduler marks slot as free
                    → next queued task gets dispatched
```

For distributed nodes, the same events are published to the broker topic, so every
subscriber (other nodes, dashboards, monitoring) sees the same state transitions.

**No shared memory, no locks** — this is the core scalability guarantee.

---

## 10. Event Sourcing Suitability

**Verdict**: AGP already IS an event-sourced system. The EventStore is the event log.
`MemoryEventStore` / `SqliteEventStore` already ship.

For full event sourcing:

- Every `RuntimeNode` writes all events to its EventStore
- Session state can be reconstructed from the log alone
- `command.session.resume {from_seq: N}` replays events N..latest to reconnecting clients
- Projections (dashboards, metrics) are just EventStore readers

At very large scale, prefer a durable append-only store with indexed reads by `(session, seq)` — same projection model as today, different backing DB.

---

## 11. Fault Tolerance Model

**Supervision hierarchy** (actor model):

```text
RuntimeNode (supervisor)
  ├── WorkerPool (supervisor)
  │   └── Worker (supervised actor)
  │       On crash → restart with backoff (max 3x) → emit error.transient
  │       On 3rd crash → remove from pool → emit error.fatal
  └── Scheduler (supervised)
      On deadlock → drain queue → restart
```

**Worker health monitoring**: every worker has a `health_check()` coroutine.
`WorkerPool` runs a background probe every `health_interval_s` (default 30s).
Unhealthy workers are drained (no new tasks) and restarted.

**Task timeout enforcement**: every `WorkerTask` has an optional `timeout_ms`.
`asyncio.wait_for` wraps the `worker.execute()` call.
On `TimeoutError`: emit `error.transient` + retry if policy allows.

**Retry policy**:

```python
@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_ms: int = 1000          # first retry delay
    backoff_multiplier: float = 2.0 # exponential backoff
    retryable_errors: set[str] = field(default_factory=lambda: {"timeout", "transient"})
```

---

## 12. Scalability considerations

Rough **current** sizing assumptions for the in-process runtime:

| Dimension         | Typical range                   |
| ----------------- | ------------------------------- |
| Workers per node  | 1–8                             |
| Sessions per node | up to ~100 (workload-dependent) |
| Nodes             | 1                               |
| Event throughput  | ~1k/s order of magnitude        |
| State store       | in-process / SQLite             |

**Bottleneck note**: event translation runs in the asyncio loop; very high event rates may need a dedicated outbound path.

Multi-node coordination, broker-backed queues, and hosted control planes are **not** part of this baseline document.

---

## 13. Runtime observability

AGP events emitted on stdio/WebSocket can also be persisted and queried via the **`--obs`** HTTP API (SQLite + REST + SSE). See [Observability architecture](../observability/architecture.md).

---

## 14. Repository layout (`agloom/runtime`)

The runtime is a single Python package: transport, AGP bridging, translation into wire events, HITL, the node/worker pool, schedulers, registries, and worker implementations all live under `agloom/runtime/`. Browse that tree in the repo for the up-to-date module list.

---

## 15. Architectural risks

| Risk                                         | Severity | Mitigation                                                              |
| -------------------------------------------- | -------- | ----------------------------------------------------------------------- |
| Worker crashes leak session state            | High     | WorkerPool supervisor restarts workers; emit `error.transient`          |
| Scheduler queue grows unbounded              | Medium   | Configurable `max_queue_depth`; back-pressure signal to frontend        |
| AGP `astream_events()` is a public hook      | Medium   | Already behind `Translator` layer; keep Translator as the only consumer |
| Single-node EventStore                       | Low      | Acceptable for local dev; scale-out swaps storage behind the same API   |
| Over-engineering distributed infra too early | High     | Ship asyncio-first; add brokers only when measured need exists          |
| Thread-safety of emitters in async pool      | Low      | Each worker gets its own emitter instance; no sharing                     |
