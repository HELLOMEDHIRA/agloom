"""Entry point for ``python -m agloom.runtime``.

Ships two transports: ``stdio`` and ``ws`` (WebSocket).

**stdio** — persistent loop reading NDJSON commands from stdin, writing AGP events to stdout.
**ws** — WebSocket server; each connection is an independent AGP session.

The **agloom CLI** (npm ``agloom-cli``, repo folder ``agloom_cli/``) is a separate Node.js package; this module only hosts the Python AGP runtime bridge.

Usage::

    python -m agloom.runtime serve --transport=stdio
    python -m agloom.runtime serve --transport=ws [--host 0.0.0.0] [--port 8765]
    python -m agloom.runtime providers list
    python -m agloom.runtime providers resolve "groq:meta-llama/llama-3.3-70b-versatile"
    python -m agloom.runtime providers verify
    python -m agloom.runtime eval eval.yaml

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
import logging
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..compat import ensure_langchain_pending_deprecation_suppressed
from ..mcp_support import MCPConnectionError
from ..protocol import SessionEmitter
from ..protocol.commands import command_adapter
from ..protocol.envelope import Envelope
from .bridge import new_session_id
from .command_dispatch import DispatchResult, dispatch_command, runtime_cli_tool_metrics, runtime_log
from .hitl import HITLBridge

_logger = logging.getLogger(__name__)


def _eprint(msg: str) -> None:
    """Print to stderr — never to stdout (stdout is AGP only)."""
    runtime_log(msg)


async def _noop_langgraph_store_cleanup() -> None:
    """No-op shutdown for in-memory / absent LangGraph stores."""
    return


def _prepare_agent_store_sqlite_path(raw: str) -> Path:
    """Resolve DB path and ensure parent dirs exist (blocking filesystem ops)."""
    db_path = Path(raw).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _agent_lt_boot_suffix(args: argparse.Namespace) -> str:
    """Clarify LT store + harness for stderr boot lines (only used when an LT store is open)."""
    kind = getattr(args, "agent_store", "sqlite")
    parts = [
        "skills + LT memory",
        "harness on when an LT store is open unless --no-harness (progress + git tools)",
    ]
    raw_path = getattr(args, "agent_store_path", ".agloom/graph_store.sqlite")
    path_disp = str(Path(raw_path).expanduser())
    if kind == "memory":
        parts.append("LT backend=InMemoryStore")
    elif kind == "sqlite-sync":
        parts.append(f"LT backend=SqliteStore (blocking) at {path_disp!r}")
    else:
        parts.append(f"LT backend=AsyncSqliteStore (aiosqlite) at {path_disp!r}")
    return "; ".join(parts)


async def _open_runtime_langgraph_store(
    args: argparse.Namespace,
) -> tuple[Any | None, Callable[[], Awaitable[None]]]:
    """Open the LangGraph store for ``create_agent`` (LT memory, skills, harness).

    Not the AGP ``--store`` (replay). Default ``sqlite`` uses async sqlite; ``sqlite-sync``
    uses blocking SqliteStore. On missing ``aiosqlite`` or open failure, falls back to
    in-memory with a stderr line.
    """
    ensure_langchain_pending_deprecation_suppressed()
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

    try:
        from langgraph.store.sqlite import AsyncSqliteStore
    except ImportError as exc:
        from langgraph.store.memory import InMemoryStore

        _eprint(
            f"[agloom-runtime] LangGraph AsyncSqliteStore unavailable ({exc!r}). "
            "Install ``aiosqlite`` for async sqlite persistence. "
            "Falling back to in-memory store (LT memory / harness state not persisted across restarts)."
        )
        return InMemoryStore(), _noop_langgraph_store_cleanup

    async_stack = AsyncExitStack()
    try:
        store = await async_stack.enter_async_context(AsyncSqliteStore.from_conn_string(conn_str))
        await store.setup()
    except Exception as exc:
        await async_stack.aclose()
        from langgraph.store.memory import InMemoryStore

        _eprint(
            f"[agloom-runtime] Could not open LangGraph sqlite store at {conn_str!r} ({exc!r}). "
            "Falling back to in-memory store."
        )
        return InMemoryStore(), _noop_langgraph_store_cleanup

    async def _cleanup_async() -> None:
        await async_stack.aclose()

    return store, _cleanup_async


def _strip_utf8_bom(line: str) -> str:
    if line.startswith("\ufeff"):
        return line[1:]
    return line


def _stdin_line_too_long(raw: bytes, *, max_line_bytes: int) -> bool:
    return max_line_bytes > 0 and len(raw) > max_line_bytes


async def _read_stdin_lines(
    queue: asyncio.Queue[str | None],
    *,
    max_line_bytes: int = 4 * 1024 * 1024,
) -> None:
    """Read stdin line-by-line; push each non-empty line onto *queue*. ``None`` signals EOF.

    Prefer :meth:`asyncio.loop.connect_read_pipe` so stdin uses asyncio stream I/O (Unix / fewer
    threads). On **Windows**, ``connect_read_pipe(sys.stdin)`` with the default Proactor loop
    often fails asynchronously with ``WinError 6`` (invalid handle) inside
    ``_ProactorReadPipeTransport`` — so we **always** use blocking ``readline`` in a thread there.

    On some platforms when driven over a pipe from Node, blocking ``readline`` has been observed
    to hit spurious EOF; fall back / primary paths balance that tradeoff per OS.
    """
    loop = asyncio.get_running_loop()
    transport: asyncio.BaseTransport | None = None
    reader: asyncio.StreamReader | None = None
    # Skip connect_read_pipe on Windows — stdin is not a reliable IOCP pipe handle (WinError 6).
    if sys.platform != "win32":
        try:
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        except (NotImplementedError, OSError, AttributeError, ValueError):
            transport = None

    if transport is None:
        pipe_stdin = not sys.stdin.isatty()
        spurious_eof_retries = 0
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except asyncio.CancelledError:
                raise
            if not line:
                # Windows + Node pipe: readline() can return "" before data arrives (not true EOF).
                if sys.platform == "win32" and pipe_stdin and spurious_eof_retries < 40:
                    spurious_eof_retries += 1
                    await asyncio.sleep(0.05)
                    continue
                _eprint("[agloom-runtime] stdin closed (EOF); exiting serve loop")
                await queue.put(None)
                return
            spurious_eof_retries = 0
            raw = line.encode("utf-8", errors="replace")
            if _stdin_line_too_long(raw, max_line_bytes=max_line_bytes):
                _eprint(f"[agloom-runtime] stdin line exceeds {max_line_bytes} bytes; dropped")
                continue
            stripped = _strip_utf8_bom(line.strip())
            if stripped:
                await queue.put(stripped)

    # Past ``transport is None`` branch: pipe connected; narrow for type checkers / safe ``close``.
    assert transport is not None
    assert reader is not None
    stream_transport: asyncio.BaseTransport = transport
    try:
        while True:
            try:
                line_bytes = await reader.readline()
            except asyncio.CancelledError:
                raise
            if not line_bytes:
                _eprint("[agloom-runtime] stdin closed (EOF); exiting serve loop")
                await queue.put(None)
                return
            if line_bytes.startswith(b"\xef\xbb\xbf"):
                line_bytes = line_bytes[3:]
            if _stdin_line_too_long(line_bytes, max_line_bytes=max_line_bytes):
                _eprint(f"[agloom-runtime] stdin line exceeds {max_line_bytes} bytes; dropped")
                continue
            line = line_bytes.decode("utf-8", errors="replace")
            stripped = _strip_utf8_bom(line.strip())
            if stripped:
                await queue.put(stripped)
    finally:
        stream_transport.close()


async def _serve_stdio(args: argparse.Namespace) -> int:
    """Persistent stdio serve loop. Returns process exit code."""
    try:
        from agloom import create_agent

        from .serve_cli import (
            apply_api_key_env,
            build_create_agent_kwargs,
            cli_tools_options_from_args,
            open_isolated_session_memory,
            resolve_llm_for_serve,
            runtime_ready_sidebar_from_args,
            session_started_snapshot_from_args,
        )
    except ImportError as exc:
        _eprint(f"[agloom-runtime] failed to import CLI helpers: {exc!r}")
        return 2

    from .session_bootstrap import (
        make_hitl_bridge,
        open_event_store_from_args,
        prepare_runtime_session,
        teardown_runtime_session,
    )
    from .workspace_bootstrap import (
        attach_session_memory_to_session_marker,
        write_session_started_json,
    )

    _cwd = Path.cwd()
    _session_arg = getattr(args, "session", None)
    _session_arg = str(_session_arg).strip() if _session_arg else None
    _thread_arg = getattr(args, "thread", None)
    _thread_arg = str(_thread_arg).strip() if _thread_arg else None
    prepared = prepare_runtime_session(
        args,
        transport="stdio",
        session_id=_session_arg,
        initial_thread=_thread_arg,
        cwd=_cwd,
    )
    session_id = prepared.session_id
    initial_thread = prepared.initial_thread
    _sd = prepared.sessions_dir
    _marker_json = prepared.marker_path
    _al_policy = prepared.allowlist
    _hitl_coalescer = prepared.coalescer
    args = prepared.working_args
    if prepared.yaml_created:
        _eprint("[agloom-runtime] wrote starter .agloom/agloom.yaml (no project config found).")

    try:
        apply_api_key_env(args)
    except Exception as exc:
        _eprint(f"[agloom-runtime] {exc}")
        return 1

    if getattr(args, "otel", False):
        try:
            from .otel_setup import configure_runtime_otel

            configure_runtime_otel()
            _eprint("[agloom-runtime] OpenTelemetry: tracer provider configured (--otel)")
        except ImportError as exc:
            _eprint(f"[agloom-runtime] --otel requires optional deps: pip install 'agloom[otel]' ({exc})")
            return 2

    store = await open_event_store_from_args(args)

    emitter = SessionEmitter(
        session=session_id,
        thread=initial_thread,
        writer=sys.stdout,
        capabilities=[],
        store=store,
    )
    hitl_bridge = make_hitl_bridge(emitter, prepared)

    lg_store, lg_store_cleanup = await _open_runtime_langgraph_store(args)
    use_harness = lg_store is not None and not getattr(args, "no_harness", False)
    if lg_store is not None:
        _eprint(
            f"[agloom-runtime] agent LT store={getattr(args, 'agent_store', 'sqlite')!r} "
            f"harness={'on' if use_harness else 'off'} "
            f"({_agent_lt_boot_suffix(args)})"
        )

    agent_holder: dict[str, Any] = {"agent": None}

    def _rewrite_session_marker(model_id: str | None = None) -> None:
        """Re-write the session JSON so it reflects the live resolved state."""
        extra = session_started_snapshot_from_args(args)
        if model_id:
            extra["model"] = model_id
            extra["llm_resolution"] = "lazy_agent_bootstrap"
        write_session_started_json(
            _sd,
            session_id,
            transport="stdio",
            thread=initial_thread,
            record_cwd=_cwd,
            hitl_tool_allowlist=sorted(_al_policy.global_tools()),
            extra=extra,
        )

    async def _ensure_agent() -> Any:
        """Resolve LLM and create agent on demand (first command that needs it)."""
        nonlocal agent_holder
        if agent_holder["agent"] is not None:
            return agent_holder["agent"]
        try:
            llm = resolve_llm_for_serve(args)
        except ImportError as exc:
            emitter.emit_error(severity="transient", message=str(exc), stage="agent.bootstrap")
            raise
        except ValueError as exc:
            msg = str(exc)
            _eprint(f"[agloom-runtime] {msg}")
            emitter.emit_error(severity="fatal", message=msg, stage="agent.bootstrap")
            raise RuntimeError(msg) from exc
        if llm is None:
            msg = (
                "no provider key set (OPENAI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY / …), "
                "or pass --model with credentials."
            )
            _eprint(f"[agloom-runtime] {msg}")
            emitter.emit_error(severity="fatal", message=msg, stage="agent.bootstrap")
            raise RuntimeError(msg)
        ca_kw = build_create_agent_kwargs(args)
        mem_cleanup_acc: list[Any] = []
        try:
            sm_mem, sm_cleanup = await open_isolated_session_memory(
                args,
                agp_session_id=session_id,
            )
            if sm_mem is not None:
                ca_kw["memory"] = sm_mem
            if sm_cleanup is not None:
                mem_cleanup_acc.append(sm_cleanup)
        except Exception as exc:
            _eprint(f"[agloom-runtime] session memory init failed: {exc!r}")
            emitter.emit_error(severity="transient", message=str(exc), stage="agent.bootstrap")
            agent_holder["_mem_cleanup"] = mem_cleanup_acc
            raise
        agent_holder["_mem_cleanup"] = mem_cleanup_acc
        try:
            agent = await create_agent(
                model=llm,
                name="agloom-runtime",
                user_callback=hitl_bridge.callback,
                store=lg_store,
                harness=use_harness,
                cli_tools=cli_tools_options_from_args(args),
                **ca_kw,
            )
        except Exception:
            for fn in mem_cleanup_acc:
                await fn()
            raise
        agent.config["_hitl_tool_allowlist"] = hitl_bridge._tool_allowlist
        agent.config["_hitl_tool_coalescer"] = _hitl_coalescer
        agent_holder["agent"] = agent
        attach_session_memory_to_session_marker(agent.config.get("memory"), _sd, session_id)
        _ct_en, _ct_ct = runtime_cli_tool_metrics(agent)
        llm_obj = agent.config.get("llm")
        model_id_guess = None
        if llm_obj is not None:
            model_id_guess = getattr(llm_obj, "model_name", None) or getattr(llm_obj, "model", None)
            if model_id_guess is None:
                model_id_guess = type(llm_obj).__name__
        tool_objs = agent.config.get("tools", []) or []
        emitter.emit_runtime_config(
            model_id=str(model_id_guess) if model_id_guess else None,
            tool_names=[getattr(t, "name", str(t)) for t in tool_objs],
            cli_tools_enabled=_ct_en,
            cli_tools_count=_ct_ct,
        )
        if agent.config.get("_mcp_servers"):
            from agloom.unified_agent import _ensure_mcp_connected

            try:
                await _ensure_mcp_connected(agent.config)
            except Exception as exc:
                msg = str(exc).strip() or repr(exc)
                _eprint(f"[agloom-runtime] {msg}")
                emitter.emit_error(
                    severity="fatal",
                    message=msg,
                    stage="mcp.bootstrap",
                    error_class=type(exc).__name__,
                )
                agent_holder["agent"] = None
                for fn in mem_cleanup_acc:
                    await fn()
                raise MCPConnectionError(msg) from exc
            rows = agent.config.get("_mcp_server_rows") or []
            if rows:
                emitter.emit_runtime_mcp_servers(
                    server_names=[str(r.get("name") or "") for r in rows],
                    servers=rows,
                )
        # Update session marker with resolved model info
        _rewrite_session_marker(model_id=str(model_id_guess) if model_id_guess else None)
        return agent

    is_resume = store is not None and await store.count(session_id) > 0
    if is_resume:
        emitter.resume(resumed_from_thread=initial_thread)
        async for evt_dict in store.replay(session_id, from_seq=0):
            emitter.write_replay_dict(evt_dict)
    else:
        emitter.open()
    _ready_sidebar = runtime_ready_sidebar_from_args(args)
    emitter.emit_runtime_ready(
        agent_name="agloom-runtime",
        harness_enabled=use_harness,
        **_ready_sidebar,
    )

    budget_tracker = None
    bt_n = getattr(args, "budget_tokens", None)
    bt_c = getattr(args, "budget_cost_usd", None)
    if (bt_n is not None and int(bt_n) > 0) or (bt_c is not None and float(bt_c) > 0):
        from ..runtime.budget_tracker import SessionBudgetTracker

        budget_tracker = SessionBudgetTracker(
            token_limit=int(bt_n) if bt_n is not None and int(bt_n) > 0 else None,
            cost_limit_usd=float(bt_c) if bt_c is not None and float(bt_c) > 0 else None,
        )
        emitter.budget_tracker = budget_tracker

    obs_store = None
    obs_server_task: asyncio.Task | None = None
    obs_ingest_tasks: set[asyncio.Task[None]] = set()
    if getattr(args, "obs", False):
        try:
            from ..observability import ObservabilityStore, make_obs_router, push_live_event

            obs_store = await ObservabilityStore.open(args.obs_db)

            # Persist and fan-out via ``on_emit`` because ``SessionEmitter._write`` is sync
            # (an async hook would yield an un-awaited coroutine).
            async def _ingest_envelope(payload: dict[str, Any]) -> None:
                try:
                    await obs_store.ingest(payload)
                except Exception:
                    _logger.exception("observability ingest failed")

            def _obs_on_emit(envelope: Envelope) -> None:
                loop = asyncio.get_running_loop()
                d = envelope.model_dump(mode="json")
                task = loop.create_task(_ingest_envelope(d), name="agp-obs-ingest")
                obs_ingest_tasks.add(task)

                def _done(t: asyncio.Task[None]) -> None:
                    obs_ingest_tasks.discard(t)

                task.add_done_callback(_done)
                push_live_event(d)

            emitter.on_emit = _obs_on_emit

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
    stdio_max_line = int(getattr(args, "stdio_max_line_bytes", 4 * 1024 * 1024) or 0)
    stdin_task = asyncio.create_task(
        _read_stdin_lines(cmd_queue, max_line_bytes=stdio_max_line),
        name="agp-stdin-reader",
    )
    invocation_tasks: set[asyncio.Task[None]] = set()
    # Explicit full-thread-id → task mapping for O(1) targeted cancellation
    thread_tasks: dict[str, asyncio.Task[None]] = {}
    shutdown = asyncio.Event()

    def _request_shutdown() -> None:
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except (NotImplementedError, OSError, ValueError):
            try:
                signal.signal(sig, lambda _s, _f, _sig=sig: _request_shutdown())
            except (OSError, ValueError):
                pass

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
                emitter.emit_error(
                    severity="transient",
                    message=f"malformed or invalid AGP command line: {exc}",
                    stage="io.command",
                )
                _eprint(f"[agloom-runtime] malformed inbound line: {exc!r}")
                continue
            try:
                result = await dispatch_command(
                    cmd,
                    agent=agent_holder.get("agent"),
                    emitter=emitter,
                    hitl_bridge=hitl_bridge,
                    ensure_agent=_ensure_agent,
                    rewrite_session_marker=lambda mid=None: _rewrite_session_marker(mid),
                    invocation_tasks=invocation_tasks,
                    thread_tasks=thread_tasks,
                    shutdown=shutdown,
                    store=store,
                    session_id=session_id,
                    budget_tracker=budget_tracker,
                    invoke_working_dir=Path(getattr(args, "cli_tools_working_dir", None) or ".").resolve(),
                )
                if result is DispatchResult.SHUTDOWN:
                    break
            except MCPConnectionError as exc:
                _eprint(f"[agloom-runtime] {exc}")
            except RuntimeError:
                pass
            except Exception as exc:
                _eprint(f"[agloom-runtime] command dispatch failed: {exc!r}")
                try:
                    emitter.emit_error(
                        severity="transient",
                        message=str(exc).strip() or repr(exc),
                        error_class=type(exc).__name__,
                        stage="dispatch",
                    )
                except Exception:
                    pass
    finally:
        shutdown.set()
        await teardown_runtime_session(
            agent=agent_holder.get("agent"),
            emitter=emitter,
            hitl_bridge=hitl_bridge,
            thread_tasks=thread_tasks,
            invocation_tasks=invocation_tasks,
            mem_cleanups=agent_holder.get("_mem_cleanup"),
            stop_heartbeat=shutdown,
            heartbeat_task=hb_task,
            close_reason="shutdown",
            lg_store_cleanup=lg_store_cleanup,
        )
        stdin_task.cancel()
        try:
            await stdin_task
        except (asyncio.CancelledError, Exception):
            pass
        if obs_ingest_tasks:
            for t in list(obs_ingest_tasks):
                if not t.done():
                    t.cancel()
            await asyncio.gather(*obs_ingest_tasks, return_exceptions=True)
        if obs_server_task and not obs_server_task.done():
            obs_server_task.cancel()
            try:
                await obs_server_task
            except (asyncio.CancelledError, Exception):
                pass
        if obs_store:
            await obs_store.close()
    return 0


async def _serve_ws(args: argparse.Namespace) -> int:
    """WebSocket serve loop — one :func:`agloom.create_agent` per accepted connection."""
    try:
        from .serve_cli import apply_api_key_env
        from .ws import serve_ws
    except ImportError as exc:
        _eprint(f"[agloom-runtime] failed to import CLI helpers: {exc!r}")
        return 2

    try:
        apply_api_key_env(args)
    except Exception as exc:
        _eprint(f"[agloom-runtime] {exc}")
        return 1

    if getattr(args, "otel", False):
        try:
            from .otel_setup import configure_runtime_otel

            configure_runtime_otel()
            _eprint("[agloom-runtime] OpenTelemetry: tracer provider configured (--otel)")
        except ImportError as exc:
            _eprint(f"[agloom-runtime] --otel requires optional deps: pip install 'agloom[otel]' ({exc})")
            return 2

    store = None
    if args.store == "sqlite":
        from ..protocol.store import SqliteEventStore
        store = SqliteEventStore(args.store_path or ".agloom/agp_events.db")
    elif args.store == "memory":
        from ..protocol.store import MemoryEventStore
        store = MemoryEventStore()

    lg_store, lg_store_cleanup = await _open_runtime_langgraph_store(args)
    use_harness = lg_store is not None and not getattr(args, "no_harness", False)
    if lg_store is not None:
        _eprint(
            f"[agloom-runtime] agent LT store={getattr(args, 'agent_store', 'sqlite')!r} "
            f"harness={'on' if use_harness else 'off'} "
            f"({_agent_lt_boot_suffix(args)})"
        )
    try:
        sub = getattr(args, "ws_subprotocol", "") or ""
        subprotocols = [sub] if sub else None
        await serve_ws(
            base_args=args,
            lg_store=lg_store,
            use_harness=use_harness,
            host=args.host,
            port=args.port,
            store=store,
            auth_token=getattr(args, "ws_token", None),
            max_size=getattr(args, "ws_max_message_bytes", None),
            max_queue=getattr(args, "ws_max_queue", None),
            subprotocols=subprotocols,
            heartbeat_interval=float(getattr(args, "heartbeat_interval", 0.0) or 0.0),
            budget_tokens=getattr(args, "budget_tokens", None),
            budget_cost_usd=getattr(args, "budget_cost_usd", None),
            attachment_working_dir=Path(getattr(args, "cli_tools_working_dir", None) or ".").resolve(),
        )
    finally:
        await lg_store_cleanup()
    return 0



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
        "--thread",
        default=None,
        help=(
            "Initial LangGraph thread id for AGP envelopes (default: random). "
            "Pass the session marker's thread when resuming so invoke/checkpoints align."
        ),
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
        "--no-require-tool-approval",
        dest="require_tool_approval",
        action="store_false",
        default=True,
        help=(
            "Allow bundled CLI tools to run without per-tool human approval (dangerous). "
            "Default: require approval for each tool when --with-cli-tools is set."
        ),
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
        "--otel",
        action="store_true",
        default=False,
        help="Enable OpenTelemetry tracing (install pip 'agloom[otel]'; uses OTEL_EXPORTER_OTLP_* or console).",
    )
    serve.add_argument(
        "--budget-tokens",
        dest="budget_tokens",
        type=int,
        default=None,
        help="Optional session-wide total token budget (input+output cumulative). Blocks command.invoke at 100%%.",
    )
    serve.add_argument(
        "--budget-cost-usd",
        dest="budget_cost_usd",
        type=float,
        default=None,
        help="Optional session-wide cumulative USD cost cap. Blocks command.invoke at 100%%.",
    )
    serve.add_argument(
        "--heartbeat-interval",
        dest="heartbeat_interval",
        type=float,
        default=30.0,
        help="Emit session.heartbeat every N seconds on stdio (0 disables). Default: 30",
    )
    serve.add_argument(
        "--stdio-max-line-bytes",
        dest="stdio_max_line_bytes",
        type=int,
        default=4 * 1024 * 1024,
        help="Drop stdin NDJSON lines larger than this many bytes. Default: 4194304",
    )
    serve.add_argument(
        "--rewrite-workspace-yaml",
        dest="rewrite_workspace_yaml",
        action="store_true",
        default=False,
        help="Allow automatic edits to .agloom/agloom.yaml (MCP shim, deprecated key stripping).",
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

    _add_serve_agent_flags(serve)

    prov = sub.add_parser("providers", help="Curated LLM provider discovery (registry-backed).")
    prov_sub = prov.add_subparsers(dest="prov_cmd", required=True)
    prov_sub.add_parser("list", help="Print slug, label, default model, env keys, pip extra.")
    prov_resolve = prov_sub.add_parser("resolve", help="Dry-run model string resolution (no LLM call).")
    prov_resolve.add_argument("spec", help='Model spec e.g. "groq:meta-llama/llama-3.3-70b-versatile"')
    prov_resolve.add_argument(
        "--provider",
        dest="provider",
        default=None,
        metavar="NAME",
        help="Same as serve --provider (optional override).",
    )
    prov_verify = prov_sub.add_parser(
        "verify",
        help="Resolve a chat model and run one minimal completion (smoke test; requires network keys).",
    )
    prov_verify.add_argument(
        "spec",
        nargs="?",
        default=None,
        metavar="MODEL",
        help='Model id (e.g. "groq:meta-llama/llama-3.3-70b-versatile"). Omit to use env auto-detect.',
    )
    prov_verify.add_argument(
        "--provider",
        dest="provider",
        default=None,
        metavar="NAME",
        help="Same as serve --provider (optional override).",
    )

    eval_p = sub.add_parser("eval", help="Run eval cases from a YAML file (substring checks).")
    eval_p.add_argument(
        "eval_file",
        nargs="?",
        default="eval.yaml",
        metavar="FILE",
        help="YAML with top-level key ``cases`` (list of {id, prompt, expect_substring?}). Default: eval.yaml",
    )
    eval_p.add_argument(
        "--seed",
        dest="eval_seed",
        type=int,
        default=None,
        metavar="N",
        help="If set, seeds Python's ``random`` module before running cases (does not fix LLM sampling).",
    )
    eval_p.add_argument(
        "--keep-going",
        dest="eval_keep_going",
        action="store_true",
        help="Run all cases after failures (exit non-zero if any case failed).",
    )
    _add_serve_agent_flags(eval_p)

    sub.add_parser("version", help="Print the installed agloom package version and exit.")

    return parser


def _add_serve_agent_flags(serve: argparse.ArgumentParser) -> None:
    """Flags forwarded into ``create_agent`` (stdio + WebSocket serve)."""
    serve.add_argument(
        "--model",
        "-m",
        dest="model",
        default=None,
        metavar="ID",
        help=(
            "Chat model id (e.g. openai:gpt-4o, anthropic:claude-3-5-sonnet-20241022). "
            "When omitted, keys are resolved from the environment as before."
        ),
    )
    serve.add_argument(
        "--provider",
        dest="provider",
        default=None,
        metavar="NAME",
        help="Force provider slug when the model id is ambiguous (same as create_agent/get_model).",
    )
    serve.add_argument(
        "--api-key-env",
        dest="api_key_env",
        default=None,
        metavar="VAR",
        help="Read the API key from this env var and map it to the provider's standard key (use with --provider or prefixed --model).",
    )
    serve.add_argument(
        "--persist-api-key-in-session-marker",
        dest="persist_api_key_in_session_marker",
        action="store_true",
        default=False,
        help=(
            "Set persist_api_key_in_session_marker: true in the session JSON (explicit audit flag). "
            "API key material is written to the marker by default unless AGLOOM_OMIT_API_KEY_FROM_SESSION=1; "
            "resume still uses inject when the target env var is empty. "
            "Dangerous: anyone who can read .agloom/sessions/*.json can use the key."
        ),
    )
    serve.add_argument(
        "--base-url",
        dest="base_url",
        default=None,
        metavar="URL",
        help=(
            "HTTP origin for OpenAI-compatible, Ollama, vLLM, LiteLLM, etc. "
            "(same as get_model base_url; also see OPENAI_BASE_URL / OLLAMA_BASE_URL / VLLM_BASE_URL)."
        ),
    )
    serve.add_argument(
        "--temperature",
        "-T",
        dest="temperature",
        type=float,
        default=None,
        metavar="F",
        help="LLM sampling temperature (passed to the provider chat model constructor).",
    )
    serve.add_argument(
        "--top-p",
        dest="top_p",
        type=float,
        default=None,
        metavar="F",
        help="Nucleus sampling top_p when the provider supports it.",
    )
    serve.add_argument(
        "--top-k",
        dest="top_k",
        type=int,
        default=None,
        metavar="N",
        help="Top-k sampling when the provider supports it (e.g. Gemini, Anthropic).",
    )
    serve.add_argument(
        "--max-tokens",
        dest="max_tokens",
        type=int,
        default=None,
        metavar="N",
        help="Max output tokens when the provider supports it.",
    )
    serve.add_argument(
        "--frequency-penalty",
        dest="frequency_penalty",
        type=float,
        default=None,
        metavar="F",
        help="OpenAI-style frequency_penalty when the provider supports it.",
    )
    serve.add_argument(
        "--presence-penalty",
        dest="presence_penalty",
        type=float,
        default=None,
        metavar="F",
        help="OpenAI-style presence_penalty when the provider supports it.",
    )
    serve.add_argument(
        "--mcp",
        action="append",
        default=[],
        metavar="SPEC",
        help="MCP server as name:path/to/config.yaml (repeatable). YAML is merged with MCPServerConfig.",
    )
    serve.add_argument("--system-prompt", dest="system_prompt", default=None, help="Inline system prompt text.")
    serve.add_argument(
        "--system-prompt-file",
        dest="system_prompt_file",
        default=None,
        metavar="PATH",
        help="Read system prompt from a UTF-8 file.",
    )
    serve.add_argument(
        "--memory",
        dest="memory_type",
        default=None,
        metavar="TYPE",
        help="Session memory backend: in-memory, none, sqlite (see --memory-path). Overrides defaults.",
    )
    serve.add_argument(
        "--memory-path",
        dest="memory_path",
        default=None,
        metavar="PATH",
        help="SQLite path when --memory=sqlite.",
    )
    serve.add_argument(
        "--skills-dir",
        dest="skills_dir",
        default=None,
        metavar="PATH",
        help="Directory for skills disk mirror (default: .agloom/skills under the process working directory).",
    )
    serve.add_argument(
        "--summarizer-model",
        dest="summarizer_model",
        default=None,
        metavar="ID",
        help="Model id for conversation summarization (defaults to main model).",
    )
    serve.add_argument(
        "--no-auto-summarize",
        dest="auto_summarize",
        action="store_false",
        default=True,
        help="Disable automatic thread summarization.",
    )
    serve.add_argument(
        "--session-max-turns",
        dest="session_max_turns",
        type=int,
        default=50,
        metavar="N",
        help="SessionMemory max_turns / rolling window size (starter YAML: memory.max_turns).",
    )


async def _providers_verify_async(args: argparse.Namespace) -> int:
    from langchain_core.messages import HumanMessage

    from agloom.llm import get_model, try_resolve_llm_from_api_keys

    spec = getattr(args, "spec", None)
    provider = getattr(args, "provider", None)
    llm = get_model(spec, provider=provider) if spec else try_resolve_llm_from_api_keys(interactive=False)
    if llm is None:
        _eprint("[agloom-runtime] providers verify: no model resolved (pass MODEL or set API keys).")
        return 1
    msg = await llm.ainvoke([HumanMessage(content="Reply with exactly the two letters OK and nothing else.")])
    text = msg.content if isinstance(msg.content, str) else str(msg.content)
    print(text.strip())
    if "OK" in text.upper():
        return 0
    _eprint("[agloom-runtime] providers verify: unexpected model output (expected OK).")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "providers":
        from agloom.llm.model_resolver import describe_resolve_dry_text, print_providers_table_text

        if args.prov_cmd == "list":
            print_providers_table_text()
            return 0
        if args.prov_cmd == "resolve":
            print(describe_resolve_dry_text(args.spec, provider=args.provider))
            return 0
        if args.prov_cmd == "verify":
            return asyncio.run(_providers_verify_async(args))
        parser.error(f"unknown providers subcommand {args.prov_cmd!r}")
        return 2
    if args.cmd == "version":
        try:
            from agloom import __version__ as agloom_ver
        except ImportError:
            agloom_ver = "unknown"
        print(agloom_ver)
        return 0
    if args.cmd == "eval":
        from agloom.eval.runner import run_eval_cli

        return run_eval_cli(args)
    if args.cmd == "serve":
        if args.transport == "ws":
            return asyncio.run(_serve_ws(args))
        return asyncio.run(_serve_stdio(args))
    parser.error(f"unknown command {args.cmd!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
