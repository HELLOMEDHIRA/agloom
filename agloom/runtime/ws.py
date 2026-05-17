"""AGP WebSocket transport — ``agloom-runtime serve --transport=ws``.

Each connecting client gets its own :class:`~agloom.protocol.emitter.AsyncSessionEmitter`
and :class:`~agloom.runtime.bridge.run_invocation` loop.  Events flow *out* as NDJSON lines
over the WebSocket; commands flow *in* as NDJSON lines in the opposite direction.

Features:

* Optional bearer-token check on the HTTP upgrade (``Authorization: Bearer …``).
* ``max_size`` / ``max_queue`` forwarded to ``websockets`` for frame limits and back-pressure.
* Optional negotiated subprotocol (default ``agp-v1``).
* Same auxiliary commands as stdio (ping, schema, tool list, subscribe, session ops, …).

TLS termination and browser CORS policies belong in a reverse proxy.

Optional dependency: ``websockets>=12.0``.  Install via::

    pip install "agloom[ws]"

**Per-connection agents:** each WebSocket client gets a dedicated :func:`agloom.create_agent`
instance (model/config from server argv + optional ``?model=…&provider=…`` query on the handshake
path). The LangGraph LT ``store`` (skills / harness) is still shared across connections unless
``--agent-store=none``. Session-scoped HITL allowlists use ``.agloom/sessions/<id>.json`` when
that directory exists (same as stdio).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import sys
import time
from uuid import uuid4
from argparse import Namespace
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
if TYPE_CHECKING:
    from agloom.protocol.store import EventStore

logger = logging.getLogger(__name__)


def _bearer_authorized(auth_header: str, token: str) -> bool:
    """Constant-time check for ``Authorization: Bearer <token>`` (length-independent digest)."""
    if not token:
        return False
    prefix = "Bearer "
    if not auth_header.startswith(prefix):
        return False
    presented = auth_header[len(prefix) :].lstrip(" \t")
    a = presented.encode("utf-8")
    b = token.encode("utf-8")
    return hmac.compare_digest(
        hashlib.sha256(a).digest(),
        hashlib.sha256(b).digest(),
    )


def _ws_request_path(ws: Any) -> str:
    req = getattr(ws, "request", None)
    if req is None:
        return ""
    return str(getattr(req, "path", "") or "")


async def serve_ws(
    *,
    base_args: Namespace,
    lg_store: Any | None,
    use_harness: bool,
    host: str = "127.0.0.1",
    port: int = 8765,
    store: EventStore | None = None,
    auth_token: str | None = None,
    max_size: int | None = 4 * 1024 * 1024,
    max_queue: int | None = 64,
    subprotocols: Sequence[str] | None = ("agp-v1",),
    heartbeat_interval: float = 0.0,
    budget_tokens: int | None = None,
    budget_cost_usd: float | None = None,
    attachment_working_dir: Path | None = None,
) -> None:
    """Start the AGP WebSocket server and block until cancelled.

    Each accepted connection builds a fresh agent using *base_args* (plus optional URL query
    overrides). ``store`` enables replay on ``command.session.resume``.
    """
    try:
        import websockets
        from websockets.asyncio.server import ServerConnection
    except ModuleNotFoundError as exc:
        sys.stderr.write(
            "agloom WebSocket transport requires 'websockets>=12.0'.\n"
            "Install with: pip install 'websockets>=12.0'\n",
        )
        raise SystemExit(1) from exc

    async def _process_request(connection: ServerConnection, request: Any) -> Any:
        if auth_token:
            auth = request.headers.get("Authorization", "")
            if not _bearer_authorized(auth, auth_token):
                return connection.respond(401, "Unauthorized")
        return None

    async def _handle(ws: ServerConnection) -> None:
        await _session_loop(
            ws,
            base_args=base_args,
            lg_store=lg_store,
            use_harness=use_harness,
            store=store,
            heartbeat_interval=heartbeat_interval,
            budget_tokens=budget_tokens,
            budget_cost_usd=budget_cost_usd,
            attachment_working_dir=attachment_working_dir,
            max_message_bytes=max_size,
        )

    proto_list: tuple[str, ...] | None = tuple(subprotocols) if subprotocols else None
    sys.stderr.write(f"[agloom-runtime] WebSocket server listening on ws://{host}:{port}\n")
    async with websockets.serve(
        _handle,
        host,
        port,
        max_size=max_size,
        max_queue=max_queue,
        subprotocols=cast(Any, proto_list),
        process_request=_process_request,
    ):
        await asyncio.Future()  # run forever


async def _session_loop(
    ws: Any,
    *,
    base_args: Namespace,
    lg_store: Any | None,
    use_harness: bool,
    store: EventStore | None,
    heartbeat_interval: float,
    budget_tokens: int | None = None,
    budget_cost_usd: float | None = None,
    attachment_working_dir: Path | None = None,
    max_message_bytes: int | None = None,
) -> None:
    """Handle one WebSocket connection as one AGP session (one agent instance)."""
    from agloom import create_agent
    from agloom.protocol import AsyncSessionEmitter, command_adapter
    from agloom.runtime.command_dispatch import DispatchResult, dispatch_command
    from agloom.runtime.serve_cli import (
        build_create_agent_kwargs,
        cli_tools_options_from_args,
        open_isolated_session_memory,
        resolve_llm_for_serve,
    )
    from agloom.runtime.session_bootstrap import (
        connect_mcp_or_raise,
        emit_agent_runtime_ready,
        make_hitl_bridge,
        prepare_runtime_session,
        teardown_runtime_session,
    )
    from agloom.runtime.workspace_bootstrap import attach_session_memory_to_session_marker

    max_line_bytes = (
        max_message_bytes if max_message_bytes is not None and max_message_bytes > 0 else 4 * 1024 * 1024
    )

    attach_wd = attachment_working_dir or Path.cwd().resolve()
    prepared = prepare_runtime_session(
        base_args,
        transport="ws",
        session_id=f"ws_{uuid4().hex[:16]}",
        cwd=attach_wd,
        ws_path_query=_ws_request_path(ws),
    )
    session_id = prepared.session_id
    initial_thread = prepared.initial_thread
    merged_args = prepared.working_args

    async def _send_error(msg: str) -> None:
        try:
            from agloom.protocol.events import ErrorData, ErrorTransient

            evt = ErrorTransient(
                session=session_id,
                thread=initial_thread,
                seq=0,
                data=ErrorData(severity="transient", message=msg, stage="ws.bootstrap"),
            )
            await ws.send(json.dumps(evt.model_dump(mode="json")) + "\n")
        except Exception:
            pass

    llm = resolve_llm_for_serve(merged_args)
    if llm is None:
        await _send_error(
            "no LLM resolved — set provider API keys in the environment or pass "
            "--model / ?model=provider:id on the WebSocket URL path query string",
        )
        return

    ca_kw = build_create_agent_kwargs(merged_args)
    mem_cleanup: Any = None
    sm_mem, mem_cleanup = await open_isolated_session_memory(merged_args, agp_session_id=session_id)
    if sm_mem is not None:
        ca_kw["memory"] = sm_mem

    emitter = AsyncSessionEmitter(
        session=session_id,
        thread=initial_thread,
        writer=ws.send,
        store=store,
        capabilities=[],
    )

    hitl_bridge = make_hitl_bridge(emitter, prepared)

    agent: Any | None = None
    try:
        agent = await create_agent(
            model=llm,
            name="agloom-runtime",
            user_callback=hitl_bridge.callback,
            store=lg_store,
            harness=use_harness,
            cli_tools=cli_tools_options_from_args(merged_args),
            **ca_kw,
        )
    except Exception as exc:
        await _send_error(f"agent initialization failed: {exc!s}")
        try:
            emitter.close(reason="error", error=str(exc))
        except Exception:
            pass
        if mem_cleanup is not None:
            await mem_cleanup()
        return

    agent.config["_hitl_tool_allowlist"] = prepared.allowlist
    attach_session_memory_to_session_marker(
        agent.config.get("memory"),
        prepared.sessions_dir,
        session_id,
    )

    budget_tracker = None
    if (budget_tokens is not None and budget_tokens > 0) or (
        budget_cost_usd is not None and budget_cost_usd > 0
    ):
        from agloom.runtime.budget_tracker import SessionBudgetTracker

        budget_tracker = SessionBudgetTracker(
            token_limit=budget_tokens if budget_tokens is not None and budget_tokens > 0 else None,
            cost_limit_usd=budget_cost_usd
            if budget_cost_usd is not None and budget_cost_usd > 0
            else None,
        )
        emitter.budget_tracker = budget_tracker

    thread_tasks: dict[str, asyncio.Task[None]] = {}
    invocation_tasks: set[asyncio.Task[None]] = set()
    mem_cleanups: list[Any] = [mem_cleanup] if mem_cleanup is not None else []

    stop_hb = asyncio.Event()
    hb_task: asyncio.Task[None] | None = None
    if heartbeat_interval > 0:
        started_mono = time.perf_counter()

        async def _heartbeat() -> None:
            while not stop_hb.is_set():
                await asyncio.sleep(heartbeat_interval)
                if stop_hb.is_set():
                    break
                emitter.emit_session_heartbeat(
                    uptime_ms=int((time.perf_counter() - started_mono) * 1000),
                )

        hb_task = asyncio.create_task(_heartbeat(), name="agp-ws-session-heartbeat")

    close_reason = "disconnect"
    async with emitter:
        emitter.open()
        try:
            await emit_agent_runtime_ready(emitter, agent, harness_enabled=use_harness)
            await connect_mcp_or_raise(agent, emitter)
        except Exception:
            await teardown_runtime_session(
                agent=agent,
                emitter=emitter,
                hitl_bridge=hitl_bridge,
                thread_tasks=thread_tasks,
                invocation_tasks=invocation_tasks,
                mem_cleanups=mem_cleanups,
                stop_heartbeat=stop_hb,
                heartbeat_task=hb_task,
                close_reason="bootstrap_failed",
            )
            return

        shutdown = asyncio.Event()
        try:
            async for raw in ws:
                if isinstance(raw, str):
                    raw_bytes = raw.encode("utf-8")
                    line = raw.strip()
                else:
                    raw_bytes = raw
                    line = raw.decode("utf-8", errors="replace").strip()
                if raw_bytes.startswith(b"\xef\xbb\xbf"):
                    raw_bytes = raw_bytes[3:]
                    line = raw_bytes.decode("utf-8", errors="replace").strip()
                if len(raw_bytes) > max_line_bytes:
                    emitter.emit_error(
                        severity="transient",
                        message=f"inbound WebSocket line exceeds {max_line_bytes} bytes",
                        stage="io.command",
                    )
                    continue
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    cmd = command_adapter.validate_python(payload)
                except Exception as exc:
                    emitter.emit_error(
                        severity="transient",
                        message=f"bad command: {exc}",
                        stage="io.command",
                    )
                    continue
                try:
                    result = await dispatch_command(
                        cmd,
                        agent=agent,
                        emitter=emitter,
                        hitl_bridge=hitl_bridge,
                        invocation_tasks=invocation_tasks,
                        thread_tasks=thread_tasks,
                        shutdown=shutdown,
                        store=store,
                        session_id=session_id,
                        budget_tracker=budget_tracker,
                        invoke_working_dir=attach_wd,
                    )
                except Exception as exc:
                    logger.exception("ws command dispatch failed: %s", exc)
                    emitter.emit_error(
                        severity="transient",
                        message=str(exc),
                        stage="io.command",
                    )
                    continue
                if result is DispatchResult.SHUTDOWN:
                    close_reason = "shutdown"
                    break

        except Exception as exc:
            try:
                from websockets.exceptions import ConnectionClosed

                if isinstance(exc, ConnectionClosed):
                    close_reason = "disconnect"
                else:
                    logger.exception("ws session %s error: %s", session_id, exc)
            except ImportError:
                logger.exception("ws session %s error: %s", session_id, exc)
        finally:
            await teardown_runtime_session(
                agent=agent,
                emitter=emitter,
                hitl_bridge=hitl_bridge,
                thread_tasks=thread_tasks,
                invocation_tasks=invocation_tasks,
                mem_cleanups=mem_cleanups,
                stop_heartbeat=stop_hb,
                heartbeat_task=hb_task,
                close_reason=close_reason,
            )
