# Embedding the runtime

Use this guide when **your process** owns the transport (stdio, WebSocket, HTTP, tests) but you want the **same agent behavior** and **AGP event stream** as the official CLI and web workspace.

!!! tip "Not building a custom server?"
    If you only call `create_agent` inside your app, you do **not** need this page. Use [Streaming & events](../features/streaming.md) (`astream_agp_events`) or run the stock **`agloom-runtime serve`** process and connect a client.

---

## Minimal bridge: one prompt → AGP stream

The smallest integration runs one user message and writes **newline-delimited JSON (NDJSON)** AGP events to your writer (stdout, socket, log file):

```python
import asyncio
import sys

from agloom import create_agent
from agloom.protocol import SessionEmitter
from agloom.runtime import new_session_id, run_invocation

async def main():
    agent = await create_agent(model=llm, name="embed-demo")
    session = new_session_id()
    thread = "thread_demo"

    emitter = SessionEmitter(session=session, thread=thread, writer=sys.stdout.write)
    await run_invocation(
        agent=agent,
        prompt="Hello",
        thread=thread,
        emitter=emitter,
    )

asyncio.run(main())
```

**What you get on the wire**

1. `session.opened` — session metadata  
2. `message.user` — the prompt  
3. Progress events — `pattern.classified`, `thinking.step`, `token.delta`, tool events, workers, metrics  
4. `message.assistant` — final answer  
5. `session.closed` — clean shutdown  

Same ordering the [CLI](https://agloom.readthedocs.io/en/latest/_packages/agloom_cli/) and [web workspace](https://agloom.readthedocs.io/en/latest/_packages/agloom_web/) expect.

**Convenience helper:** `run_invocation_to_writer` creates the emitter for you (ideal in tests).

---

## When to add a runtime node

For **multiple queued invocations**, health checks, or isolated tool workers in one process, use a **runtime node** — a small coordinator that schedules work and fans out AGP events:

```python
from agloom import create_agent
from agloom.protocol import AsyncSessionEmitter
from agloom.runtime import RuntimeNode

agent = await create_agent(model=llm)
emitter = AsyncSessionEmitter(session="s1", thread="t1", writer=your_async_writer)
node = RuntimeNode.create_local(agent=agent, emitter=emitter)

await node.start()
await node.submit_invoke(
    prompt="Read README and summarize",
    thread="t1",
    session="s1",
    emitter=emitter,
)
await node.stop()
```

Use an **async** writer so the event loop is not blocked while flushing NDJSON.

| Need | Approach |
| ---- | -------- |
| Single request/response in tests | `run_invocation` / `run_invocation_to_writer` |
| Chat server with many sessions | `agloom-runtime serve` + WebSocket |
| Custom queue inside your app | `RuntimeNode` + `submit_invoke` |
| Only Python, no NDJSON | `agent.astream_agp_events()` (no emitter setup) |

---

## Human-in-the-loop and cancellation

Pass a **HITL bridge** into `run_invocation` when you must distinguish user cancel vs process shutdown — the same behavior as `agloom-runtime serve`. Your transport should forward `command.hitl.respond` envelopes while a run is paused.

Details: [Human-in-the-Loop](../features/hitl.md) · [AGP commands](../protocol/agp.md).

---

## See also

- [AGP from Python](agp-python.md) — parse and emit envelopes in tests  
- [AGP specification](../protocol/agp.md) — full event catalog  
- [Runtime architecture](../runtime/architecture.md) — how `serve` fits together (operators)
