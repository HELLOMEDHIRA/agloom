"""Entry point for ``python -m agloom.runtime``.

Ships two transports: ``stdio`` and ``ws`` (WebSocket).

**stdio** — persistent loop reading NDJSON commands from stdin, writing AGP events to stdout.
**ws** — WebSocket server; each connection is an independent AGP session.

The **agloom CLI** (npm ``agloom-cli``, repo folder ``agloom_cli/``) is a separate Node.js package; this module only hosts the Python AGP runtime bridge.

Usage::

    python -m agloom.runtime serve --transport=stdio
    python -m agloom.runtime serve --transport=ws [--host 0.0.0.0] [--port 8765]

Inbound (one JSON per line)::

    {"type": "command.invoke",          "data": {"prompt": "...", "thread": "t_xyz"}}
    {"type": "command.cancel",          "data": {"thread": "t_xyz"}}
    {"type": "command.hitl.respond",    "data": {"request_id": "hr_…", "decision": "accept"}}
    {"type": "command.worker.assign",   "data": {"worker_id": "w_1", "task": "..."}}
    {"type": "command.session.resume",  "data": {"thread": "t_xyz", "from_seq": 5}}
    {"type": "command.runtime.shutdown"}

Outbound follows the AGP envelope — see ``agloom/docs/protocol/agp.md``.
Diagnostic lines go to **stderr** so stdout stays a clean event stream.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..protocol import SessionEmitter
from ..protocol.commands import (
    CommandCancel,
    CommandConfigSet,
    CommandFeedback,
    CommandHITLRespond,
    CommandInvoke,
    CommandPing,
    CommandRuntimeShutdown,
    CommandSchemaRequest,
    CommandSessionCreate,
    CommandSessionDelete,
    CommandSessionList,
    CommandSessionResume,
    CommandSnapshotRequest,
    CommandSubscribe,
    CommandToolInvoke,
    CommandToolList,
    CommandUnsubscribe,
    CommandWorkerAssign,
    command_adapter,
)
from ..protocol.envelope import Envelope
from .bridge import new_session_id, run_invocation
from .hitl import HITLBridge


def _eprint(msg: str) -> None:
    """Print to stderr — never to stdout (stdout is AGP only)."""
    print(msg, file=sys.stderr, flush=True)


def _cli_tools_options_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    if not getattr(args, "with_cli_tools", False):
        return None
    return {
        "working_dir": getattr(args, "cli_tools_working_dir", ".") or ".",
        "allow_shell": not getattr(args, "cli_tools_no_shell", False),
        "allow_network": not getattr(args, "cli_tools_no_network", False),
        "sandbox": not getattr(args, "cli_tools_no_sandbox", False),
    }


def _runtime_cli_tool_metrics(agent: Any) -> tuple[bool, int]:
    from ..cli_tools import CLI_TOOL_NAMES

    tool_objs = getattr(agent, "config", {}).get("tools", []) or []
    names = {getattr(t, "name", None) for t in tool_objs}
    count = sum(1 for n in names if n in CLI_TOOL_NAMES)
    return count > 0, count


def _hitl_allowlist_runtime_setup(args: argparse.Namespace) -> tuple[set[str], Path | None]:
    """Load persisted tool allowlist (``decision=allowlist``); optional path disabled via flags."""
    from .hitl_allowlist import load_tool_allowlist

    if getattr(args, "no_hitl_allowlist_persist", False):
        return set(), None
    raw = getattr(args, "hitl_allowlist_path", None)
    path = Path.cwd() / ".agloom" / "hitl_tool_allowlist.json"
    if isinstance(raw, str) and raw.strip():
        path = Path(raw).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return load_tool_allowlist(path), path


async def _noop_langgraph_store_cleanup() -> None:
    """No-op shutdown for in-memory / absent LangGraph stores."""
    return


def _prepare_agent_store_sqlite_path(raw: str) -> Path:
    """Resolve DB path and ensure parent dirs exist (blocking filesystem ops)."""
    db_path = Path(raw).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


async def _open_runtime_langgraph_store(
    args: argparse.Namespace,
) -> tuple[Any | None, Callable[[], Awaitable[None]]]:
    """Open the LangGraph BaseStore used by ``create_agent`` (skills, LT memory tools, harness).

    Separate from ``--store`` (AGP EventStore / replay). Default **sqlite** uses LangGraph's
    **AsyncSqliteStore** (aiosqlite) so reads/writes do not block the asyncio event loop.

    ``sqlite-sync`` uses the blocking ``SqliteStore`` for niche tooling only.
    """
    kind = getattr(args, "agent_store", "sqlite")
    if kind == "none":
        return None, _noop_langgraph_store_cleanup

    if kind == "memory":
        from langgraph.store.memory import InMemoryStore

        return InMemoryStore(), _noop_langgraph_store_cleanup

    raw = getattr(args, "agent_store_path", ".agloom/graph_store.sqlite")
    db_path = await asyncio.to_thread(_prepare_agent_store_sqlite_path, raw)
    conn_str = str(db_path)

    if kind == "sqlite-sync":
        from contextlib import ExitStack

        from langgraph.store.sqlite import SqliteStore

        sync_stack = ExitStack()
        store = sync_stack.enter_context(SqliteStore.from_conn_string(conn_str))
        store.setup()

        def _sync_cleanup() -> None:
            sync_stack.close()

        async def _cleanup_sync_wrapper() -> None:
            await asyncio.to_thread(_sync_cleanup)

        return store, _cleanup_sync_wrapper

    from langgraph.store.sqlite import AsyncSqliteStore

    async_stack = AsyncExitStack()
    store = await async_stack.enter_async_context(AsyncSqliteStore.from_conn_string(conn_str))
    await store.setup()

    async def _cleanup_async() -> None:
        await async_stack.aclose()

    return store, _cleanup_async


async def _read_stdin_lines(queue: asyncio.Queue[str | None]) -> None:
    """Read stdin line-by-line in a thread; push each non-empty line onto *queue*. ``None``
    sentinel signals EOF so the main loop can drain and exit cleanly."""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            await queue.put(None)
            return
        stripped = line.strip()
        if stripped:
            await queue.put(stripped)


async def _serve_stdio(args: argparse.Namespace) -> int:
    """Persistent stdio serve loop. Returns process exit code."""
    try:
        from agloom.llm import try_resolve_llm_from_api_keys
    except ImportError as exc:
        _eprint(f"[agloom-runtime] failed to import CLI helpers: {exc!r}")
        return 2

    llm = try_resolve_llm_from_api_keys(interactive=False)
    if llm is None:
        _eprint(
            "[agloom-runtime] no provider key set (OPENAI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY / …). "
            "Export one and re-run."
        )
        return 1

    from agloom import create_agent

    store = None
    if args.store == "sqlite":
        from ..protocol.store import SqliteEventStore
        store = SqliteEventStore(args.store_path or "agp_events.db")
    elif args.store == "memory":
        from ..protocol.store import MemoryEventStore
        store = MemoryEventStore()

    session_id = args.session or new_session_id()
    initial_thread = f"thread_{uuid4().hex[:16]}"
    emitter = SessionEmitter(
        session=session_id,
        thread=initial_thread,
        writer=sys.stdout,
        capabilities=[],
        store=store,
    )
    _al_set, _al_path = _hitl_allowlist_runtime_setup(args)
    hitl_bridge = HITLBridge(emitter, tool_allowlist=_al_set, allowlist_persist_path=_al_path)

    lg_store, lg_store_cleanup = await _open_runtime_langgraph_store(args)
    use_harness = lg_store is not None and not getattr(args, "no_harness", False)
    if lg_store is not None:
        _eprint(
            f"[agloom-runtime] agent LT store={getattr(args, 'agent_store', 'sqlite')!r} "
            f"harness={'on' if use_harness else 'off'} "
            "(skills + LT memory tools + optional harness; sqlite=async aiosqlite)"
        )

    agent: Any
    try:
        agent = await create_agent(
            model=llm,
            name="agloom-runtime",
            user_callback=hitl_bridge.callback,
            store=lg_store,
            harness=use_harness,
            cli_tools=_cli_tools_options_from_args(args),
        )
    except Exception:
        await lg_store_cleanup()
        raise

    agent.config["_hitl_tool_allowlist"] = _al_set

    emitter.open()

    agent_label = getattr(agent, "config", {}).get("name", "agloom-runtime")
    _ct_en, _ct_ct = _runtime_cli_tool_metrics(agent)
    emitter.emit_runtime_ready(agent_name=str(agent_label), cli_tools_enabled=_ct_en, cli_tools_count=_ct_ct)
    llm_obj = getattr(agent, "config", {}).get("llm")
    model_id_guess = None
    if llm_obj is not None:
        model_id_guess = getattr(llm_obj, "model_name", None) or getattr(llm_obj, "model", None)
        if model_id_guess is None:
            model_id_guess = type(llm_obj).__name__
    tool_objs = getattr(agent, "config", {}).get("tools", []) or []
    emitter.emit_runtime_config(
        model_id=str(model_id_guess) if model_id_guess else None,
        tool_names=[getattr(t, "name", str(t)) for t in tool_objs],
        cli_tools_enabled=_ct_en,
        cli_tools_count=_ct_ct,
    )

    obs_store = None
    obs_server_task: asyncio.Task | None = None
    if getattr(args, "obs", False):
        try:
            from ..observability import ObservabilityStore, make_obs_router, push_live_event

            obs_store = await ObservabilityStore.open(args.obs_db)

            # Persist and fan-out via ``on_emit`` because ``SessionEmitter._write`` is sync
            # (an async hook would yield an un-awaited coroutine).
            def _obs_on_emit(envelope: Envelope) -> None:
                loop = asyncio.get_running_loop()
                d = envelope.model_dump(mode="json")
                loop.create_task(obs_store.ingest(d))  # noqa: RUF006
                push_live_event(d)

            emitter.on_emit = _obs_on_emit  # type: ignore[attr-defined]

            import uvicorn
            from fastapi import FastAPI
            obs_app = FastAPI(title="agloom observability", docs_url="/docs")
            obs_app.include_router(make_obs_router(obs_store), prefix="/observe")

            obs_config = uvicorn.Config(obs_app, host="127.0.0.1", port=args.obs_port, log_level="warning")
            obs_server = uvicorn.Server(obs_config)
            obs_server_task = asyncio.create_task(obs_server.serve(), name="agp-obs-server")
            _eprint(f"[agloom-runtime] observability API at http://127.0.0.1:{args.obs_port}/observe")
        except Exception as exc:
            _eprint(f"[agloom-runtime] observability startup failed: {exc!r}")

    cmd_queue: asyncio.Queue[str | None] = asyncio.Queue()
    stdin_task = asyncio.create_task(_read_stdin_lines(cmd_queue), name="agp-stdin-reader")
    invocation_tasks: set[asyncio.Task[None]] = set()
    # Explicit full-thread-id → task mapping for O(1) targeted cancellation
    thread_tasks: dict[str, asyncio.Task[None]] = {}
    shutdown = asyncio.Event()

    hb_interval = float(getattr(args, "heartbeat_interval", 30.0) or 0.0)
    hb_task: asyncio.Task[None] | None = None
    if hb_interval > 0:
        started_mono = time.perf_counter()

        async def _session_heartbeat_loop() -> None:
            while not shutdown.is_set():
                await asyncio.sleep(hb_interval)
                if shutdown.is_set():
                    break
                emitter.emit_session_heartbeat(uptime_ms=int((time.perf_counter() - started_mono) * 1000))

        hb_task = asyncio.create_task(_session_heartbeat_loop(), name="agp-session-heartbeat")

    try:
        while not shutdown.is_set():
            line = await cmd_queue.get()
            if line is None:
                break
            try:
                payload = json.loads(line)
                cmd = command_adapter.validate_python(payload)
            except (json.JSONDecodeError, Exception) as exc:
                _eprint(f"[agloom-runtime] dropping malformed inbound line: {exc!r}")
                continue
            await _dispatch_command(
                cmd,
                agent=agent,
                emitter=emitter,
                hitl_bridge=hitl_bridge,
                invocation_tasks=invocation_tasks,
                thread_tasks=thread_tasks,
                shutdown=shutdown,
                store=store,
                session_id=session_id,
            )
    finally:
        shutdown.set()
        if hb_task is not None:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
        for t in invocation_tasks:
            if not t.done():
                hitl_bridge.prepare_invocation_cancel(t, reason="shutdown")
                t.cancel()
        if invocation_tasks:
            await asyncio.gather(*invocation_tasks, return_exceptions=True)
        hitl_bridge.cancel_all()
        stdin_task.cancel()
        try:
            await stdin_task
        except (asyncio.CancelledError, Exception):
            pass
        emitter.close(reason="shutdown")
        await agent.aclose()
        await lg_store_cleanup()
        if obs_server_task and not obs_server_task.done():
            obs_server_task.cancel()
        if obs_store:
            await obs_store.close()
    return 0


async def _serve_ws(args: argparse.Namespace) -> int:
    """WebSocket serve loop."""
    try:
        from agloom.llm import try_resolve_llm_from_api_keys
    except ImportError as exc:
        _eprint(f"[agloom-runtime] failed to import CLI helpers: {exc!r}")
        return 2

    llm = try_resolve_llm_from_api_keys(interactive=False)
    if llm is None:
        _eprint("[agloom-runtime] no provider key set.")
        return 1

    from agloom import create_agent

    from .invocation_context import runtime_hitl_user_callback
    from .ws import serve_ws

    store = None
    if args.store == "sqlite":
        from ..protocol.store import SqliteEventStore
        store = SqliteEventStore(args.store_path or "agp_events.db")
    elif args.store == "memory":
        from ..protocol.store import MemoryEventStore
        store = MemoryEventStore()

    # One shared agent; each WS connection gets its own emitter/session and LangGraph thread id.
    lg_store, lg_store_cleanup = await _open_runtime_langgraph_store(args)
    use_harness = lg_store is not None and not getattr(args, "no_harness", False)
    shared_agent: Any | None = None
    if lg_store is not None:
        _eprint(
            f"[agloom-runtime] agent LT store={getattr(args, 'agent_store', 'sqlite')!r} "
            f"harness={'on' if use_harness else 'off'} "
            "(skills + LT memory tools + optional harness; sqlite=async aiosqlite)"
        )
    try:
        _ws_al_set, _ws_al_path = _hitl_allowlist_runtime_setup(args)
        shared_agent = await create_agent(
            model=llm,
            name="agloom-runtime",
            user_callback=runtime_hitl_user_callback,
            store=lg_store,
            harness=use_harness,
            cli_tools=_cli_tools_options_from_args(args),
        )
        shared_agent.config["_hitl_tool_allowlist"] = _ws_al_set

        async def _agent_factory() -> Any:
            assert shared_agent is not None
            return shared_agent

        sub = getattr(args, "ws_subprotocol", "") or ""
        subprotocols = [sub] if sub else None
        await serve_ws(
            agent_factory=_agent_factory,
            host=args.host,
            port=args.port,
            store=store,
            auth_token=getattr(args, "ws_token", None),
            max_size=getattr(args, "ws_max_message_bytes", None),
            max_queue=getattr(args, "ws_max_queue", None),
            subprotocols=subprotocols,
            heartbeat_interval=float(getattr(args, "heartbeat_interval", 0.0) or 0.0),
            hitl_allowlist_persist_path=_ws_al_path,
        )
    finally:
        if shared_agent is not None:
            await shared_agent.aclose()
        await lg_store_cleanup()
    return 0


async def _dispatch_command(
    cmd: Any,
    *,
    agent: Any,
    emitter: SessionEmitter,
    hitl_bridge: HITLBridge,
    invocation_tasks: set[asyncio.Task[None]],
    thread_tasks: dict[str, asyncio.Task[None]],
    shutdown: asyncio.Event,
    store: Any = None,
    session_id: str = "",
) -> None:
    """Route one typed command to its handler."""

    if isinstance(cmd, CommandRuntimeShutdown):
        shutdown.set()
        return

    if isinstance(cmd, CommandHITLRespond):
        ok = hitl_bridge.respond(
            cmd.data.request_id,
            cmd.data.decision,
            text=cmd.data.text,
            actor=cmd.data.actor,
        )
        if not ok:
            _eprint(f"[agloom-runtime] no pending HITL request for id={cmd.data.request_id!r}")
        return

    if isinstance(cmd, CommandInvoke):
        thread = cmd.data.thread or f"thread_{uuid4().hex[:16]}"
        inv_emitter = emitter.fork_for_thread(thread)
        task = asyncio.create_task(
            run_invocation(
                agent=agent,
                prompt=cmd.data.prompt,
                thread=thread,
                emitter=inv_emitter,
                hitl_bridge=hitl_bridge,
            ),
            name=f"agp-invocation-{thread[:8]}",
        )
        hitl_bridge.bind_task_emitter(task, inv_emitter, thread=thread)
        invocation_tasks.add(task)
        thread_tasks[thread] = task

        def _on_done_invocation(t: asyncio.Task[None]) -> None:
            invocation_tasks.discard(t)
            thread_tasks.pop(thread, None)

        task.add_done_callback(_on_done_invocation)
        return

    if isinstance(cmd, CommandCancel):
        target_thread = cmd.data.thread
        cancelled_n = 0
        if target_thread is not None:
            # O(1) exact match via the explicit mapping
            task = thread_tasks.get(target_thread)
            if task and not task.done():
                hitl_bridge.prepare_invocation_cancel(task, reason="user_aborted")
                task.cancel()
                cancelled_n = 1
                # Cancel only HITL requests bound to this specific thread
                hitl_bridge.cancel_for_thread(target_thread)
        else:
            # No specific thread — cancel everything
            for t in list(invocation_tasks):
                if not t.done():
                    hitl_bridge.prepare_invocation_cancel(t, reason="user_aborted")
                    t.cancel()
                    cancelled_n += 1
            hitl_bridge.cancel_all()
        if not cancelled_n:
            _eprint(
                f"[agloom-runtime] command.cancel matched no invocations"
                f"{f' (thread={target_thread!r})' if target_thread else ''}"
            )
        return

    if isinstance(cmd, CommandWorkerAssign):
        wthread = cmd.data.thread or f"wt_{uuid4().hex[:12]}"
        w_emitter = emitter.fork_for_thread(wthread)
        # Emit worker.spawned so the supervisor sees the task has been dispatched.
        w_emitter.emit_worker_spawned(
            worker_id=cmd.data.worker_id,
            name=cmd.data.worker_id,
            pattern=cmd.data.pattern,
            task=cmd.data.task,
        )
        wtask = asyncio.create_task(
            run_invocation(
                agent=agent,
                prompt=cmd.data.task,
                thread=wthread,
                emitter=w_emitter,
                hitl_bridge=hitl_bridge,
            ),
            name=f"agp-worker-{cmd.data.worker_id[:8]}",
        )
        hitl_bridge.bind_task_emitter(wtask, w_emitter, thread=wthread)
        invocation_tasks.add(wtask)
        thread_tasks[wthread] = wtask

        def _on_done_worker(t: asyncio.Task[None]) -> None:
            invocation_tasks.discard(t)
            thread_tasks.pop(wthread, None)

        wtask.add_done_callback(_on_done_worker)
        _eprint(f"[agloom-runtime] worker {cmd.data.worker_id!r} dispatched on thread={wthread!r}")
        return

    if isinstance(cmd, CommandSessionResume):
        from_seq = cmd.data.from_seq or 0
        if store is not None:
            emitter.resume(resumed_from_thread=cmd.data.thread, replayed_from_seq=from_seq if from_seq > 0 else None)
            async for evt_dict in store.replay(session_id, from_seq=from_seq):
                json_line = json.dumps(evt_dict, ensure_ascii=False)
                sys.stdout.write(json_line + "\n")
                sys.stdout.flush()
        else:
            emitter.resume(resumed_from_thread=cmd.data.thread)
        return

    if isinstance(cmd, CommandFeedback):
        # Forward feedback to the agent's feedback handler (NoOp when not configured).
        feedback_handler = getattr(agent, "config", {}).get("feedback_handler")
        if feedback_handler is None:
            _eprint("[agloom-runtime] command.feedback received but no feedback_handler configured")
        else:
            try:
                await feedback_handler.on_feedback(
                    run_id=cmd.data.run_id,
                    rating=cmd.data.rating,
                    comment=cmd.data.comment,
                    correct=cmd.data.correct,
                    metadata=cmd.data.metadata,
                )
            except Exception as exc:
                _eprint(f"[agloom-runtime] feedback handler error: {exc!r}")
        # Always emit the wire event so frontends can track it regardless.
        emitter.emit_feedback_scored(
            run_id=cmd.data.run_id,
            rating=cmd.data.rating,
            comment=cmd.data.comment,
            correct=cmd.data.correct,
            metadata=cmd.data.metadata,
        )
        return

    if isinstance(cmd, CommandSnapshotRequest):
        # Trigger a manual checkpoint save and emit checkpoint.saved.
        checkpointer = getattr(agent, "config", {}).get("checkpointer")
        label = cmd.data.label
        thread = cmd.data.thread or session_id
        if checkpointer is None:
            _eprint("[agloom-runtime] command.snapshot.request: no checkpointer configured")
        else:
            try:
                from ..models import ExecutionResult, PatternType
                from ..unified_agent import _save_checkpoint
                dummy_result = ExecutionResult(
                    pattern_used=PatternType.DIRECT,
                    query="",
                    output="",
                    steps_taken=0,
                    success=True,
                    run_id=f"snap_{uuid4().hex[:8]}",
                )
                await _save_checkpoint(checkpointer, thread, dummy_result, "snapshot")
                emitter.emit_checkpoint_saved(thread=thread, label=label)
            except Exception as exc:
                _eprint(f"[agloom-runtime] snapshot failed: {exc!r}")
        return

    if isinstance(cmd, CommandPing):
        emitter.emit_runtime_pong(ping_id=cmd.data.ping_id)
        return

    if isinstance(cmd, CommandSchemaRequest):
        from ..protocol.schema import build_schema

        emitter.emit_runtime_schema(json_schema=build_schema())
        return

    if isinstance(cmd, CommandToolList):
        tools = getattr(agent, "config", {}).get("tools", []) or []
        rows: list[tuple[str, str | None]] = []
        for t in tools:
            nm = getattr(t, "name", "?")
            desc = getattr(t, "description", None)
            rows.append((nm, str(desc) if desc else None))
        emitter.emit_runtime_tools(tools=rows)
        return

    if isinstance(cmd, CommandSubscribe):
        emitter.set_subscription_prefixes(cmd.data.prefixes if cmd.data.prefixes else None)
        return

    if isinstance(cmd, CommandUnsubscribe):
        emitter.clear_subscription()
        return

    if isinstance(cmd, CommandSessionList):
        if store is None:
            emitter.emit_error(
                severity="transient",
                message="command.session.list requires --store",
                stage="session.list",
            )
            emitter.emit_runtime_sessions(sessions=[])
        else:
            ids = await store.list_session_ids()
            emitter.emit_runtime_sessions(sessions=ids)
        return

    if isinstance(cmd, CommandSessionCreate):
        sid = cmd.data.session_id or new_session_id()
        emitter.emit_runtime_session_created(session_id=sid)
        return

    if isinstance(cmd, CommandSessionDelete):
        if store is None:
            emitter.emit_error(
                severity="transient",
                message="command.session.delete requires --store",
                stage="session.delete",
            )
        else:
            await store.clear(cmd.data.session_id)
        return

    if isinstance(cmd, CommandToolInvoke):
        raw_sz = len(json.dumps(cmd.data.arguments, ensure_ascii=False))
        if raw_sz > 32_000:
            emitter.emit_runtime_tool_result(ok=False, error="arguments too large")
            return
        tools = getattr(agent, "config", {}).get("tools", []) or []
        tool = next((x for x in tools if getattr(x, "name", None) == cmd.data.name), None)
        if tool is None:
            emitter.emit_runtime_tool_result(ok=False, error="unknown_tool")
            return
        try:
            out = await tool.ainvoke(cmd.data.arguments)
            emitter.emit_runtime_tool_result(ok=True, result=out)
        except Exception as exc:
            emitter.emit_runtime_tool_result(ok=False, error=str(exc))
        return

    if isinstance(cmd, CommandConfigSet):
        try:
            from agloom.unified_agent import resolve_model

            agent.config["llm"] = resolve_model(cmd.data.model_id)
        except Exception as exc:
            emitter.emit_error(severity="transient", message=str(exc), stage="config.set")
            return
        _cta, _ctb = _runtime_cli_tool_metrics(agent)
        emitter.emit_runtime_config_applied(
            model_id=cmd.data.model_id,
            cli_tools_enabled=_cta,
            cli_tools_count=_ctb,
        )
        llm_after = agent.config.get("llm")
        mid = getattr(llm_after, "model_name", None) or getattr(llm_after, "model", None)
        if mid is None and llm_after is not None:
            mid = type(llm_after).__name__
        tools_after = agent.config.get("tools", []) or []
        emitter.emit_runtime_config(
            model_id=str(mid) if mid else cmd.data.model_id,
            tool_names=[getattr(t, "name", str(t)) for t in tools_after],
            cli_tools_enabled=_cta,
            cli_tools_count=_ctb,
        )
        return

    _eprint(f"[agloom-runtime] unsupported command type: {type(cmd).__name__!r}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agloom.runtime",
        description="Agloom Protocol (AGP) runtime — multi-transport bridge (stdio + WebSocket).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run the AGP bridge (stdio or WebSocket).")
    serve.add_argument(
        "--transport",
        choices=("stdio", "ws"),
        default="stdio",
        help="Transport layer: 'stdio' (default) or 'ws' (WebSocket, requires agloom[ws]).",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="WebSocket host (only used when --transport=ws). Default: 127.0.0.1",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=8765,
        help="WebSocket port (only used when --transport=ws). Default: 8765",
    )
    serve.add_argument(
        "--session",
        default=None,
        help="Override the session id (otherwise minted automatically).",
    )
    serve.add_argument(
        "--store",
        choices=("none", "memory", "sqlite"),
        default="none",
        help="EventStore backend for replay/resume. Default: none (disabled).",
    )
    serve.add_argument(
        "--store-path",
        dest="store_path",
        default=None,
        help="SQLite db path (only used when --store=sqlite). Default: agp_events.db",
    )
    serve.add_argument(
        "--agent-store",
        choices=("none", "memory", "sqlite", "sqlite-sync"),
        default="sqlite",
        help=(
            "LangGraph store for skills, LT memory tools, and harness. "
            "Default: sqlite (AsyncSqliteStore / aiosqlite). "
            "sqlite-sync = blocking SqliteStore for niche sync tooling."
        ),
    )
    serve.add_argument(
        "--agent-store-path",
        dest="agent_store_path",
        default=".agloom/graph_store.sqlite",
        help="SQLite path for --agent-store=sqlite or sqlite-sync. Default: .agloom/graph_store.sqlite",
    )
    serve.add_argument(
        "--no-harness",
        action="store_true",
        default=False,
        help="Disable harness tools (progress + git). LT memory and skills stay on if --agent-store is not none.",
    )
    serve.add_argument(
        "--with-cli-tools",
        dest="with_cli_tools",
        action="store_true",
        default=False,
        help="Inject built-in CLI tools (filesystem, optional shell/network, meta). Off by default.",
    )
    serve.add_argument(
        "--cli-tools-working-dir",
        dest="cli_tools_working_dir",
        default=".",
        help="Working directory root for sandboxed CLI tools (with --with-cli-tools). Default: .",
    )
    serve.add_argument(
        "--cli-tools-no-shell",
        dest="cli_tools_no_shell",
        action="store_true",
        default=False,
        help="Disable shell tools: execute, bash, and bash_background (start/status/stop).",
    )
    serve.add_argument(
        "--cli-tools-no-network",
        dest="cli_tools_no_network",
        action="store_true",
        default=False,
        help="Disable fetch_url, read_url_markdown, and web_search.",
    )
    serve.add_argument(
        "--cli-tools-no-sandbox",
        dest="cli_tools_no_sandbox",
        action="store_true",
        default=False,
        help="Allow absolute paths outside --cli-tools-working-dir (dangerous).",
    )
    serve.add_argument(
        "--hitl-allowlist-path",
        dest="hitl_allowlist_path",
        default=None,
        help=(
            "JSON file backing persistent HITL tool allowlist (wire decision=allowlist). "
            "Default when omitted: .agloom/hitl_tool_allowlist.json under cwd."
        ),
    )
    serve.add_argument(
        "--no-hitl-allowlist-persist",
        dest="no_hitl_allowlist_persist",
        action="store_true",
        default=False,
        help="Disable loading/saving the HITL tool allowlist file (memory-only for this process).",
    )
    serve.add_argument(
        "--obs",
        action="store_true",
        default=False,
        help="Enable observability store (writes to --obs-db). Activates /observe API on --obs-port.",
    )
    serve.add_argument(
        "--obs-db",
        dest="obs_db",
        default="agloom_obs.db",
        help="Observability SQLite database path. Default: agloom_obs.db",
    )
    serve.add_argument(
        "--obs-port",
        dest="obs_port",
        type=int,
        default=8766,
        help="HTTP port for the observability REST/SSE API (when --obs is set). Default: 8766",
    )
    serve.add_argument(
        "--heartbeat-interval",
        dest="heartbeat_interval",
        type=float,
        default=30.0,
        help="Emit session.heartbeat every N seconds on stdio (0 disables). Default: 30",
    )
    serve.add_argument(
        "--ws-token",
        dest="ws_token",
        default=None,
        help="When --transport=ws, require Authorization: Bearer <token> on the handshake.",
    )
    serve.add_argument(
        "--ws-max-message-bytes",
        dest="ws_max_message_bytes",
        type=int,
        default=4 * 1024 * 1024,
        help="WebSocket max incoming message size (bytes). Default: 4194304",
    )
    serve.add_argument(
        "--ws-max-queue",
        dest="ws_max_queue",
        type=int,
        default=64,
        help="WebSocket inbound frame queue high-water mark. Default: 64",
    )
    serve.add_argument(
        "--ws-subprotocol",
        dest="ws_subprotocol",
        default="agp-v1",
        help="Negotiated WebSocket subprotocol (empty string to disable). Default: agp-v1",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "serve":
        if args.transport == "ws":
            return asyncio.run(_serve_ws(args))
        return asyncio.run(_serve_stdio(args))
    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
