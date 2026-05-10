"""AGP WebSocket transport — ``agloom-runtime serve --transport=ws``.

Each connecting client gets its own :class:`~agloom.protocol.emitter.AsyncSessionEmitter`
and :class:`~agloom.runtime.bridge.run_invocation` loop.  Events flow *out* as NDJSON lines
over the WebSocket; commands flow *in* as NDJSON lines in the opposite direction.

The implementation is intentionally minimal (no auth, no TLS termination — run behind a
reverse proxy for production):

* Connection → ``session.opened`` emitted immediately.
* Inbound JSON line parsed via :data:`~agloom.protocol.command_adapter`.
* ``command.invoke`` → spawns an asyncio task that drives ``run_invocation``.
* ``command.cancel`` → cancels the matching task.
* ``command.hitl.respond`` → forwarded to :class:`~agloom.runtime.hitl.HITLBridge`.
* ``command.session.resume`` → replays buffered events from the :class:`~agloom.protocol.store.EventStore`.
* ``command.runtime.shutdown`` → graceful shutdown.
* Unknown commands → logged, not fatal.

Optional dependency: ``websockets>=12.0``.  Install via::

    pip install "agloom[ws]"

or directly::

    pip install "websockets>=12.0"
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from agloom.protocol.store import EventStore

logger = logging.getLogger(__name__)


async def serve_ws(
    *,
    agent_factory: Any,
    host: str = "127.0.0.1",
    port: int = 8765,
    store: EventStore | None = None,
) -> None:
    """Start the AGP WebSocket server and block until SIGINT/SIGTERM.

    ``agent_factory`` is a callable ``() -> UnifiedAgent`` (or any object with
    ``astream_events``).  Called once per connection — each session gets a fresh
    agent with its own in-process state.

    ``store`` is an optional :class:`~agloom.protocol.store.EventStore` wired into
    every emitter for replay-on-reconnect.

    Example::

        from agloom import create_agent
        from agloom.runtime.ws import serve_ws

        async def main():
            await serve_ws(agent_factory=lambda: create_agent(name="bot", llm=my_llm))

        asyncio.run(main())
    """
    try:
        import websockets  # type: ignore[import-untyped]
        from websockets.asyncio.server import ServerConnection  # type: ignore[import-untyped]
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            "agloom WebSocket transport requires 'websockets>=12.0'.\n"
            "Install with: pip install 'websockets>=12.0'\n",
        )
        raise SystemExit(1) from exc

    async def _handle(ws: ServerConnection) -> None:
        await _session_loop(ws, agent_factory=agent_factory, store=store)

    sys.stderr.write(f"[agloom-runtime] WebSocket server listening on ws://{host}:{port}\n")
    async with websockets.serve(_handle, host, port):
        await asyncio.Future()  # run forever


async def _session_loop(ws: Any, *, agent_factory: Any, store: EventStore | None) -> None:
    """Handle one WebSocket connection as one AGP session."""
    from agloom.protocol import AsyncSessionEmitter, command_adapter
    from agloom.protocol.commands import (
        CommandCancel,
        CommandHITLRespond,
        CommandInvoke,
        CommandRuntimeShutdown,
        CommandSessionResume,
        CommandWorkerAssign,
    )
    from agloom.runtime.bridge import run_invocation
    from agloom.runtime.hitl import HITLBridge

    session_id = f"ws_{uuid4().hex[:16]}"
    agent = agent_factory()

    emitter = AsyncSessionEmitter(
        session=session_id,
        thread=f"t_{uuid4().hex[:12]}",
        writer=ws.send,
        store=store,
    )

    hitl_bridge = HITLBridge(emitter)

    # Active invocation tasks keyed by thread id.
    _tasks: dict[str, asyncio.Task[None]] = {}

    async def _send_error(msg: str) -> None:
        try:
            await ws.send(json.dumps({"type": "error.transient", "data": {"message": msg}}) + "\n")
        except Exception:
            pass

    async with emitter:
        emitter.open()

        try:
            async for raw in ws:
                line = raw.strip() if isinstance(raw, str) else raw.decode().strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    cmd = command_adapter.validate_python(payload)
                except Exception as exc:
                    await _send_error(f"bad command: {exc}")
                    continue

                if isinstance(cmd, CommandInvoke):
                    thread = cmd.data.thread or f"t_{uuid4().hex[:12]}"
                    inv_emitter = emitter.fork_for_thread(thread)
                    task: asyncio.Task[None] = asyncio.create_task(
                        run_invocation(
                            agent=agent,
                            prompt=cmd.data.prompt,
                            thread=thread,
                            emitter=inv_emitter,
                            hitl_bridge=hitl_bridge,
                        ),
                        name=f"invoke-{thread}",
                    )
                    hitl_bridge.bind_task_emitter(task, inv_emitter)
                    _tasks[thread] = task

                elif isinstance(cmd, CommandCancel):
                    if cmd.data.thread:
                        task_to_cancel = _tasks.get(cmd.data.thread)
                        if task_to_cancel and not task_to_cancel.done():
                            hitl_bridge.prepare_invocation_cancel(task_to_cancel, reason="user_aborted")
                            task_to_cancel.cancel()
                    else:
                        for t in list(_tasks.values()):
                            if not t.done():
                                hitl_bridge.prepare_invocation_cancel(t, reason="user_aborted")
                                t.cancel()

                elif isinstance(cmd, CommandHITLRespond):
                    hitl_bridge.respond(
                        request_id=cmd.data.request_id,
                        decision=cmd.data.decision,
                        text=cmd.data.text,
                        actor=cmd.data.actor,
                    )

                elif isinstance(cmd, CommandSessionResume):
                    from_seq = cmd.data.from_seq or 0
                    if store is not None:
                        emitter.resume(resumed_from_thread=cmd.data.thread, replayed_from_seq=from_seq if from_seq > 0 else None)
                        async for evt_dict in store.replay(session_id, from_seq=from_seq):
                            await ws.send(json.dumps(evt_dict) + "\n")
                    else:
                        emitter.resume(resumed_from_thread=cmd.data.thread)

                elif isinstance(cmd, CommandWorkerAssign):
                    # In-process worker stub — Phase 1.
                    from agloom.runtime.bridge import run_invocation as _run_inv

                    wthread = cmd.data.thread or f"wt_{uuid4().hex[:12]}"
                    w_emitter = emitter.fork_for_thread(wthread)
                    inv_emitter_w: AsyncSessionEmitter = w_emitter  # type: ignore[assignment]
                    wtask: asyncio.Task[None] = asyncio.create_task(
                        _run_inv(
                            agent=agent,
                            prompt=cmd.data.task,
                            thread=wthread,
                            emitter=inv_emitter_w,
                            hitl_bridge=hitl_bridge,
                        ),
                        name=f"worker-{cmd.data.worker_id}-{wthread}",
                    )
                    hitl_bridge.bind_task_emitter(wtask, inv_emitter_w)
                    _tasks[wthread] = wtask

                elif isinstance(cmd, CommandRuntimeShutdown):
                    for t in list(_tasks.values()):
                        if not t.done():
                            hitl_bridge.prepare_invocation_cancel(t, reason="shutdown")
                            t.cancel()
                    emitter.close(reason="shutdown")
                    break

        except Exception as exc:
            logger.exception("ws session %s error: %s", session_id, exc)
        finally:
            for t in list(_tasks.values()):
                if not t.done():
                    hitl_bridge.prepare_invocation_cancel(t, reason="shutdown")
                    t.cancel()
            if _tasks:
                await asyncio.gather(*_tasks.values(), return_exceptions=True)
            emitter.close()
