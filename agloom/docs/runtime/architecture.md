# agloom-runtime Architecture

**Status**: Phase 1 (foundations shipped) | **Version**: 1.0  
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

| Concern | agloom-core | agloom-runtime |
|---|---|---|
| Orchestration semantics | ✅ LangGraph graphs | ❌ |
| Memory / knowledge | ✅ LTM, episodic, session | ❌ |
| Tools / MCP | ✅ tool definitions, adapters | ❌ |
| Agent logic / patterns | ✅ REACT, SUPERVISOR, etc. | ❌ |
| LangGraph checkpoints | ✅ saves/restores | runtime triggers |
| **Worker lifecycle** | ❌ | ✅ |
| **Task scheduling** | ❌ | ✅ |
| **Distributed routing** | ❌ | ✅ |
| **Fault tolerance** | ❌ | ✅ |
| **Transport layer** | ❌ | ✅ stdio / ws / HTTP |
| **Execution observability** | emits AgentEvents | ✅ translates → AGP |

The boundary is clean: `agloom-core` produces `AsyncGenerator[AgentEvent]`;
`agloom-runtime` wraps that in a `Worker`, routes tasks to it, and translates
the resulting events onto the AGP wire.

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

```
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

### Worker Types (current + roadmap)

| Type | Phase | Description |
|---|---|---|
| `LocalAIWorker` | **P1** | Wraps `UnifiedAgent.astream_events`, runs in-process |
| `ToolWorker` | **P1** | Executes a single tool call in isolation |
| `SubprocessWorker` | **P2** | Spawns a child process, streams its stdout as AGP |
| `RemoteHTTPWorker` | **P2** | POSTs tasks to a remote `agloom-runtime` endpoint |
| `RemoteWSWorker` | **P2** | Maintains a persistent WS connection to a remote node |
| `RayWorker` | **P3** | Dispatches tasks to a Ray cluster |
| `GPUInferenceWorker` | **P3** | Wraps vLLM / Ollama / TGI for GPU-bound inference |
| `SparkWorker` | **P4** | Submits Spark jobs, streams structured progress events |
| `EmbeddingWorker` | **P3** | Batch embedding tasks (sentence-transformers, OpenAI) |
| `BrowserWorker` | **P3** | Playwright automation, streams DOM/network events |

### Worker Capability Tags

Workers declare capabilities as string tags. The scheduler matches tasks to workers:

```
"agent:react"           "agent:supervisor"     "agent:cot"
"tool:filesystem"       "tool:web_search"      "tool:code_exec"
"inference:gpu"         "inference:cpu"
"embed:dense"           "embed:sparse"
"spark"                 "ray"                  "flink"
"browser"               "network"
```

---

## 5. Scheduling Model

**Phase 1**: Single-node priority queue (asyncio-native, zero infrastructure)

```
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

**Phase 2+**: Pluggable scheduler backends
- `InProcessScheduler` — current asyncio queue
- `RedisScheduler` — multi-process, same host (Redis Streams / Sorted Sets)
- `BrokerScheduler` — multi-host (RabbitMQ / Kafka / NATS as transport)

---

## 6. AGP Runtime Messaging Flow

```
Frontend (agloom CLI)
  │
  │  command.invoke {prompt, thread, session}
  ▼
RuntimeNode._dispatch_command()
  │
  ├── wrap as WorkerTask {task_type="agent.invoke", required_caps=["agent:*"]}
  │
  ▼
Scheduler.submit(task)
  │
  ├── pop task when worker available
  │
  ▼
WorkerPool.route(task) → LocalAIWorker.execute(task, emitter)
  │
  │  AgentEvent stream (classify / thinking / token / tool / done)
  ▼
Translator.translate(event) → AGP Envelope
  │
  ▼
AsyncSessionEmitter._write(envelope) → stdout NDJSON / WebSocket frame
  │
  ▼
Frontend receives: pattern.classified / thinking.step / token.delta /
                   tool.call / tool.result / message.assistant
```

**Worker assignment** for distributed execution uses two new AGP commands:
```json
{"type":"command.worker.assign","data":{"worker_id":"w_gpu_1","task_id":"t_42","payload":{...}}}
{"type":"worker.spawned",       "data":{"worker_id":"w_gpu_1","name":"gpu-inference"}}
{"type":"worker.completed",     "data":{"worker_id":"w_gpu_1","output_preview":"..."}}
```

---

## 7. Remote Worker Communication Strategy

Three patterns, chosen by deployment need:

### Pattern A — Direct AGP over WebSocket (P2)
Remote worker runs `agloom-runtime serve --transport=ws`.
Supervisor runtime connects as a WebSocket client and sends `command.worker.assign`.
Worker streams AGP events back over the same connection.

```
Supervisor RuntimeNode ──WS──► Remote Worker RuntimeNode
  send: command.worker.assign         recv: worker.spawned
  recv: AGP event stream  ◄───        emit: token.delta, message.assistant, ...
```

### Pattern B — AGP over Message Broker (P3)
Each `RuntimeNode` publishes/subscribes to topics on a broker (NATS / Kafka).
Topic naming: `agp.session.<session_id>.commands` / `agp.session.<session_id>.events`.
Enables fan-out to multiple consumers (dashboards, monitoring, logging).

### Pattern C — Cloud Control Plane (P4)
`agloom-cloud` control plane manages worker registration and assignment.
Workers register capabilities; control plane matches tasks to workers globally.
Heartbeat + capability refresh every 30s.

---

## 8. Checkpoint / Recovery Architecture

LangGraph checkpoints remain entirely inside `agloom-core`. The runtime's role is:

1. **Trigger**: `command.snapshot.request` → calls `agent._save_checkpoint()` in core
2. **Observe**: `checkpoint.saved` / `checkpoint.restored` events on the AGP wire
3. **Resume**: `command.session.resume {thread, from_seq}` → replay EventStore →
   LangGraph restores from checkpoint → AGP stream continues

```
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

**EventStore backends** (already implemented):
- `MemoryEventStore` — single process, no persistence
- `SqliteEventStore` — single host, survives restarts
- **P2**: `PostgresEventStore` — multi-host, production grade
- **P3**: `CassandraEventStore` — large-scale audit log

---

## 9. State Synchronisation

Workers share no mutable state. All coordination happens through events:

```
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

The missing piece for true event sourcing at scale: **P2 PostgresEventStore with
append-only write path and indexed reads by `(session, seq)`**.

---

## 11. Fault Tolerance Model

**Supervision hierarchy** (actor model):

```
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

## 12. Scalability Considerations

| Dimension | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Workers per node | 1–8 | 1–32 | unlimited (auto-scale) |
| Sessions per node | 100 | 1000 | 10000 |
| Nodes | 1 | 2–10 | 100+ |
| Event throughput | ~1k/s | ~10k/s | ~1M/s (broker-backed) |
| State store | in-process | SQLite | PostgreSQL / Cassandra |

**Key bottleneck to address early**: the `Translator` is synchronous inside an async
loop. For high-throughput (>10k events/s), move to a dedicated translation thread.

---

## 13. Multi-Runtime Coordination

**P2 — Peer-to-peer**: RuntimeNodes discover each other through a shared registry
(Redis / etcd). Each node exposes a WebSocket endpoint. Tasks are routed to nodes
with matching capabilities.

**P3 — Control plane**: A lightweight `agloom-coordinator` service holds global
worker and session topology. RuntimeNodes register on startup and receive routing
tables. The coordinator is stateless (uses PostgresEventStore as source of truth).

**P4 — Kubernetes operator**: `AgloomRuntime` CRD. The operator manages pod
lifecycle, scales worker replicas based on queue depth, and injects AGP routing
config via environment variables.

---

## 14. Runtime Observability Architecture

Every AGP event emitted by any worker is an observation. The observability stack is:

```
Worker
  │ AgentEvents
  ▼
Translator → AGP Envelopes
  │
  ├──► AsyncSessionEmitter → stdio/ws (to frontend)
  │
  ├──► EventStore (append-only audit log)
  │
  └──► MetricsCollector (future P2)
           ├── Prometheus counter: agp_events_total{type, session}
           ├── Histogram: worker_task_duration_ms{worker_type}
           └── Gauge: worker_pool_active_tasks
```

**P2 additions**:
- `metric.tokens` events aggregated to Prometheus `agp_tokens_total{model, phase}`
- OpenTelemetry trace spans per `WorkerTask` (trace_id = thread_id)
- Grafana dashboard seeded from Prometheus

---

## 15. Future Compatibility

### agloom-cloud
RuntimeNode already has the right interface: `serve --transport=ws` exposes
a WebSocket endpoint. `agloom-cloud` is a control plane that:
1. Issues `command.worker.assign` to RuntimeNodes
2. Aggregates AGP event streams from all nodes
3. Provides session replay via centralized EventStore

### Dashboards
AGP events are already structured enough to drive real-time dashboards.
A `DashboardAdapter` subscribes to all sessions, aggregates `metric.tokens`,
`worker.spawned`, `tool.call` events, and writes to a time-series store.

### Deployment systems
`WorkerPool` already supports dynamic `register_worker()` / `deregister_worker()`.
Kubernetes HPA can scale worker replicas; the operator calls these APIs via a
sidecar health+register endpoint.

### VSCode extension
Same as agloom CLI: spawn `agloom-runtime serve --transport=ws`, connect from the
extension's WebSocket client, render AGP events in a custom webview panel.

---

## 16. Package / Repository Structure

```
agloom/
  runtime/
    __init__.py         # public API: RuntimeNode, WorkerPool, Scheduler, ...
    __main__.py         # CLI entry: `agloom-runtime serve`
    bridge.py           # run_invocation, session helpers (existing)
    hitl.py             # HITLBridge (existing)
    translator.py       # AgentEvent → AGP Envelope (existing)
    ws.py               # WebSocket transport (existing)
    node.py             # ★ NEW: RuntimeNode assembly
    pool.py             # ★ NEW: WorkerPool + health monitor
    workers/
      __init__.py       # BaseWorker ABC (★ NEW)
      types.py          # WorkerTask, WorkerHealth, RetryPolicy (★ NEW)
      local.py          # LocalAIWorker (★ NEW)
      tool.py           # ToolWorker (★ NEW)
      subprocess.py     # SubprocessWorker (P2)
      remote_http.py    # RemoteHTTPWorker (P2)
      remote_ws.py      # RemoteWSWorker (P2)
      ray.py            # RayWorker (P3)
      gpu.py            # GPUInferenceWorker (P3)
    scheduler/
      __init__.py       # Scheduler ABC + InProcessScheduler (★ NEW)
      redis.py          # RedisScheduler (P2)
      broker.py         # BrokerScheduler (P3)
    registry/
      __init__.py       # WorkerRegistry + InMemoryRegistry (★ NEW)
      redis.py          # RedisRegistry (P2)
      etcd.py           # EtcdRegistry (P3)
    state/              # (P2 — PostgresEventStore etc.)
```

---

## 17. Phased Implementation Roadmap

### Phase 1 — Runtime Foundations (NOW, this PR)
- [x] `WorkerTask` / `WorkerHealth` / `RetryPolicy` data models
- [x] `BaseWorker` ABC
- [x] `LocalAIWorker` (wraps `UnifiedAgent`)
- [x] `ToolWorker` (isolated tool execution)
- [x] `InProcessScheduler` (asyncio priority queue + capability matching)
- [x] `InMemoryRegistry`
- [x] `WorkerPool` with health monitor
- [x] `RuntimeNode` assembly
- [x] `__main__.py` integration

### Phase 2 — Remote Workers + Persistence (next sprint)
- [ ] `SubprocessWorker` — child process worker
- [ ] `RemoteHTTPWorker` + `RemoteWSWorker`
- [ ] `RedisScheduler` + `RedisRegistry`
- [ ] `PostgresEventStore`
- [ ] Worker health endpoint (`GET /health`)
- [ ] Prometheus metrics exporter

### Phase 3 — GPU + Specialised Workers
- [ ] `GPUInferenceWorker` (vLLM / Ollama)
- [ ] `EmbeddingWorker` (sentence-transformers batch)
- [ ] `BrowserWorker` (Playwright)
- [ ] `RayWorker`
- [ ] OpenTelemetry trace integration

### Phase 4 — Cluster + Cloud
- [ ] `agloom-coordinator` control plane service
- [ ] Kubernetes operator (`AgloomRuntime` CRD)
- [ ] `CassandraEventStore`
- [ ] `BrokerScheduler` (NATS / Kafka)
- [ ] Multi-node session routing

---

## 18. Architectural Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Worker crashes leak session state | High | WorkerPool supervisor restarts workers; emit `error.transient` |
| Scheduler queue grows unbounded | Medium | Configurable `max_queue_depth`; back-pressure signal to frontend |
| AGP `astream_events()` is a public hook | Medium | Already behind `Translator` layer; keep Translator as the only consumer |
| Single EventStore per RuntimeNode (Phase 1) | Low | Acceptable for local; Phase 2 adds PostgreSQL |
| Over-engineering distributed infra too early | High | **Phased approach enforced**: Phase 1 is pure asyncio, zero infra deps |
| Thread-safety of `Translator` in async pool | Low | Each worker gets its own `AsyncSessionEmitter` instance; no sharing |
