# Embedding the runtime (`agloom.runtime`)

Use this module when you want **your** process to own I/O (TCP, WebSocket, stdin/out, tests) while still running the same **`UnifiedAgent`** pipeline and emitting **AGP** through a **`SessionEmitter`** or **`AsyncSessionEmitter`**.

## Bridge: one-shot invocation → AGP

The smallest integration is the bridge — it opens the session, records the user turn, streams **`AgentEvent`** instances from **`astream_events`**, translates each to AGP via **`translate`**, and closes with **`completed`** or **`error`**.

```python
from agloom import create_agent
from agloom.protocol import SessionEmitter
from agloom.runtime import run_invocation, new_session_id

agent = await create_agent(model=llm, name="embed-demo")
emitter = SessionEmitter(session=new_session_id(), thread="thread_demo", writer=sys.stdout.write)
await run_invocation(agent=agent, prompt="Hello", thread="thread_demo", emitter=emitter)
```

- **`run_invocation_to_writer`** — constructs the emitter for you (session/thread ids optional) and returns the closed emitter (handy in tests).
- **`translate`** — maps a single **`AgentEvent`** to emitter calls if you are building a custom loop.
- **`HITLBridge`** — pass into **`run_invocation`** when cancellations must distinguish user abort vs runtime shutdown (same as `agloom-runtime serve`).

See module docstring and **`agloom/runtime/bridge.py`** for exact lifecycle (**`session.opened`**, **`message.user`**, **`session.closed`**, **`error.fatal`** ordering).

## `RuntimeNode` — scheduler + worker pool (Phase 1)

For multi-task queues and health-aware workers, **`RuntimeNode`** bundles **`WorkerPool`**, **`InProcessScheduler`**, and **`InMemoryRegistry`**. **`RuntimeNode.create_local`** wires one **`LocalAIWorker`** around your agent.

```python
from agloom import create_agent
from agloom.protocol import AsyncSessionEmitter
from agloom.runtime import RuntimeNode

agent = await create_agent(model=llm)
emitter = AsyncSessionEmitter(session="s1", thread="t1", writer=some_async_writer)
node = RuntimeNode.create_local(agent=agent, emitter=emitter)
await node.start()
await node.submit_invoke(prompt="Read README", thread="t1", session="s1", emitter=emitter)
await node.stop()
```

Use an async-capable **`writer`** (or the emitter’s context manager — see **`AsyncSessionEmitter`** docstring) so the drain task can flush NDJSON without blocking the event loop.

Public symbols include **`WorkerPool`**, **`BaseWorker`**, **`LocalAIWorker`**, **`Scheduler`**, **`InProcessScheduler`**, **`SchedulerFullError`**, **`WorkerRegistry`**, **`InMemoryRegistry`**, **`WorkerTask`**, **`WorkerHealth`**, **`WorkerStatus`**, **`WorkerType`**, **`TaskStatus`**, **`RetryPolicy`**. These are **supported** for Phase 1 local execution and custom worker registration; remote/pluggable backends are expected to grow without breaking the names imported from **`agloom.runtime`**.

## See also

- [AGP from Python](agp-python.md) — parsing and emitting envelopes
- [Runtime architecture](../runtime/architecture.md) — how `agloom-runtime serve` fits together
