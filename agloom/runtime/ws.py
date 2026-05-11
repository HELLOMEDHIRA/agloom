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
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
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
    auth_token: str | None = None,
    max_size: int | None = 4 * 1024 * 1024,
    max_queue: int | None = 64,
    subprotocols: Sequence[str] | None = ("agp-v1",),
    heartbeat_interval: float = 0.0,
    hitl_allowlist_persist_path: Path | None = None,
    budget_tokens: int | None = None,
    budget_cost_usd: float | None = None,
    attachment_working_dir: Path | None = None,
) -> None:
    """Start the AGP WebSocket server and block until cancelled.

    ``agent_factory`` is invoked once per connection. ``store`` enables replay on
    ``command.session.resume``.
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

    async def _process_request(connection: ServerConnection, request: Any) -> Any:
        if auth_token:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {auth_token}":
                return connection.respond(401, "Unauthorized")
        return None

    async def _handle(ws: ServerConnection) -> None:
        await _session_loop(
            ws,
            agent_factory=agent_factory,
            store=store,
            heartbeat_interval=heartbeat_interval,
            hitl_allowlist_persist_path=hitl_allowlist_persist_path,
            budget_tokens=budget_tokens,
            budget_cost_usd=budget_cost_usd,
            attachment_working_dir=attachment_working_dir,
        )

    proto_list: tuple[str, ...] | None = tuple(subprotocols) if subprotocols else None
    sys.stderr.write(f"[agloom-runtime] WebSocket server listening on ws://{host}:{port}\n")
    async with websockets.serve(
        _handle,
        host,
        port,
        max_size=max_size,
        max_queue=max_queue,
        subprotocols=proto_list,  # type: ignore[arg-type]
        process_request=_process_request,
    ):
        await asyncio.Future()  # run forever


async def _session_loop(
    ws: Any,
    *,
    agent_factory: Any,
    store: EventStore | None,
    heartbeat_interval: float,
    hitl_allowlist_persist_path: Path | None = None,
    budget_tokens: int | None = None,
    budget_cost_usd: float | None = None,
    attachment_working_dir: Path | None = None,
) -> None:
    """Handle one WebSocket connection as one AGP session."""
    from agloom.protocol import AsyncSessionEmitter, command_adapter
    from agloom.protocol.commands import (
        CommandAttachFile,
        CommandCancel,
        CommandConfigSet,
        CommandFeedback,
        CommandHITLRespond,
        CommandInvoke,
        CommandPing,
        CommandProvidersList,
        CommandRuntimeShutdown,
        CommandSchemaRequest,
        CommandSessionCreate,
        CommandSessionDelete,
        CommandSessionList,
        CommandSessionRename,
        CommandSessionResume,
        CommandSnapshotRequest,
        CommandSubscribe,
        CommandToolInvoke,
        CommandToolList,
        CommandUnsubscribe,
        CommandWorkerAssign,
    )
    from agloom.multimodal import prepare_invoke_command
    from agloom.runtime.bridge import new_session_id, run_invocation
    from agloom.runtime.hitl import HITLBridge
    from agloom.runtime.workspace_bootstrap import ensure_agloom_workspace, write_session_started_json

    session_id = f"ws_{uuid4().hex[:16]}"
    initial_thread = f"t_{uuid4().hex[:12]}"
    attach_wd = attachment_working_dir or Path.cwd().resolve()
    _sessions_dir, _ = ensure_agloom_workspace(attach_wd)
    write_session_started_json(
        _sessions_dir,
        session_id,
        transport="ws",
        thread=initial_thread,
        record_cwd=attach_wd,
    )
    agent = agent_factory()

    emitter = AsyncSessionEmitter(
        session=session_id,
        thread=initial_thread,
        writer=ws.send,
        store=store,
        capabilities=[],
    )

    cfg = cast("dict[str, Any]", agent.config)
    if not isinstance(cfg.get("_hitl_tool_allowlist"), set):
        cfg["_hitl_tool_allowlist"] = set()
    _al_set = cfg["_hitl_tool_allowlist"]
    hitl_bridge = HITLBridge(
        emitter,
        tool_allowlist=_al_set,
        allowlist_persist_path=hitl_allowlist_persist_path,
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
        emitter.budget_tracker = budget_tracker  # type: ignore[attr-defined]

    _tasks: dict[str, asyncio.Task[None]] = {}

    async def _send_error(msg: str) -> None:
        try:
            await ws.send(json.dumps({"type": "error.transient", "data": {"message": msg}}) + "\n")
        except Exception:
            pass

    stop_hb = asyncio.Event()
    hb_task: asyncio.Task[None] | None = None
    if heartbeat_interval > 0:
        started_mono = time.perf_counter()

        async def _heartbeat() -> None:
            while not stop_hb.is_set():
                await asyncio.sleep(heartbeat_interval)
                if stop_hb.is_set():
                    break
                emitter.emit_session_heartbeat(uptime_ms=int((time.perf_counter() - started_mono) * 1000))

        hb_task = asyncio.create_task(_heartbeat(), name="agp-ws-session-heartbeat")

    async with emitter:
        emitter.open()

        from agloom.cli_tools import CLI_TOOL_NAMES

        agent_label = getattr(agent, "config", {}).get("name", "agloom-runtime")
        tool_objs = getattr(agent, "config", {}).get("tools", []) or []
        _names = {getattr(t, "name", None) for t in tool_objs}
        _ct_ct = sum(1 for n in _names if n in CLI_TOOL_NAMES)
        _ct_en = _ct_ct > 0
        emitter.emit_runtime_ready(agent_name=str(agent_label), cli_tools_enabled=_ct_en, cli_tools_count=_ct_ct)
        llm_obj = getattr(agent, "config", {}).get("llm")
        model_id_guess = None
        if llm_obj is not None:
            model_id_guess = getattr(llm_obj, "model_name", None) or getattr(llm_obj, "model", None)
            if model_id_guess is None:
                model_id_guess = type(llm_obj).__name__
        emitter.emit_runtime_config(
            model_id=str(model_id_guess) if model_id_guess else None,
            tool_names=[getattr(t, "name", str(t)) for t in tool_objs],
            cli_tools_enabled=_ct_en,
            cli_tools_count=_ct_ct,
        )

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
                    if budget_tracker is not None and budget_tracker.is_invoke_blocked():
                        emitter.emit_error(
                            severity="transient",
                            message="Session budget exhausted (tokens or cost). Raise limits via command.config.set.",
                            stage="budget.blocked",
                        )
                        continue
                    thread = cmd.data.thread or f"t_{uuid4().hex[:12]}"
                    try:
                        prompt, summaries = prepare_invoke_command(
                            cmd, agent=agent, thread=thread, working_dir=attach_wd
                        )
                    except ValueError as exc:
                        emitter.emit_error(
                            severity="transient",
                            message=str(exc),
                            stage="invoke.attachments",
                        )
                        continue
                    inv_emitter = emitter.fork_for_thread(thread)
                    task: asyncio.Task[None] = asyncio.create_task(
                        run_invocation(
                            agent=agent,
                            prompt=prompt,
                            thread=thread,
                            emitter=inv_emitter,
                            hitl_bridge=hitl_bridge,
                            user_attachments=summaries or None,
                        ),
                        name=f"invoke-{thread}",
                    )
                    hitl_bridge.bind_task_emitter(task, inv_emitter, thread=thread)
                    _tasks[thread] = task

                elif isinstance(cmd, CommandCancel):
                    if cmd.data.thread:
                        task_to_cancel = _tasks.get(cmd.data.thread)
                        if task_to_cancel and not task_to_cancel.done():
                            hitl_bridge.prepare_invocation_cancel(task_to_cancel, reason="user_aborted")
                            task_to_cancel.cancel()
                            hitl_bridge.cancel_for_thread(cmd.data.thread)
                    else:
                        for t in list(_tasks.values()):
                            if not t.done():
                                hitl_bridge.prepare_invocation_cancel(t, reason="user_aborted")
                                t.cancel()
                        hitl_bridge.cancel_all()

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
                        emitter.resume(
                            resumed_from_thread=cmd.data.thread,
                            replayed_from_seq=from_seq if from_seq > 0 else None,
                        )
                        async for evt_dict in store.replay(session_id, from_seq=from_seq):
                            await ws.send(json.dumps(evt_dict, ensure_ascii=False) + "\n")
                    else:
                        emitter.resume(resumed_from_thread=cmd.data.thread)

                elif isinstance(cmd, CommandWorkerAssign):
                    from agloom.runtime.bridge import run_invocation as _run_inv

                    wthread = cmd.data.thread or f"wt_{uuid4().hex[:12]}"
                    w_emitter = emitter.fork_for_thread(wthread)
                    w_emitter.emit_worker_spawned(
                        worker_id=cmd.data.worker_id,
                        name=cmd.data.worker_id,
                        pattern=cmd.data.pattern,
                        task=cmd.data.task,
                    )
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
                    hitl_bridge.bind_task_emitter(wtask, inv_emitter_w, thread=wthread)
                    _tasks[wthread] = wtask

                elif isinstance(cmd, CommandFeedback):
                    feedback_handler = getattr(agent, "config", {}).get("feedback_handler")
                    if feedback_handler is None:
                        logger.warning("command.feedback but no feedback_handler configured")
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
                            logger.warning("feedback handler error: %r", exc)
                    emitter.emit_feedback_scored(
                        run_id=cmd.data.run_id,
                        rating=cmd.data.rating,
                        comment=cmd.data.comment,
                        correct=cmd.data.correct,
                        metadata=cmd.data.metadata,
                    )

                elif isinstance(cmd, CommandSnapshotRequest):
                    checkpointer = getattr(agent, "config", {}).get("checkpointer")
                    label = cmd.data.label
                    thread = cmd.data.thread or session_id
                    if checkpointer is None:
                        logger.warning("command.snapshot.request: no checkpointer configured")
                    else:
                        try:
                            from agloom.models import ExecutionResult, PatternType
                            from agloom.unified_agent import _save_checkpoint

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
                            logger.warning("snapshot failed: %r", exc)

                elif isinstance(cmd, CommandPing):
                    emitter.emit_runtime_pong(ping_id=cmd.data.ping_id)

                elif isinstance(cmd, CommandSchemaRequest):
                    from agloom.protocol.schema import build_schema

                    emitter.emit_runtime_schema(json_schema=build_schema())

                elif isinstance(cmd, CommandToolList):
                    tools = getattr(agent, "config", {}).get("tools", []) or []
                    rows: list[tuple[str, str | None]] = []
                    for t in tools:
                        nm = getattr(t, "name", "?")
                        desc = getattr(t, "description", None)
                        rows.append((nm, str(desc) if desc else None))
                    emitter.emit_runtime_tools(tools=rows)

                elif isinstance(cmd, CommandProvidersList):
                    from agloom.llm.provider_registry import provider_catalog

                    emitter.emit_runtime_providers(providers=provider_catalog())

                elif isinstance(cmd, CommandSubscribe):
                    emitter.set_subscription_prefixes(cmd.data.prefixes if cmd.data.prefixes else None)

                elif isinstance(cmd, CommandUnsubscribe):
                    emitter.clear_subscription()

                elif isinstance(cmd, CommandSessionList):
                    if store is None:
                        emitter.emit_error(
                            severity="transient",
                            message="command.session.list requires EventStore",
                            stage="session.list",
                        )
                        emitter.emit_runtime_sessions(sessions=[])
                    else:
                        ids = await store.list_session_ids()
                        emitter.emit_runtime_sessions(sessions=ids)

                elif isinstance(cmd, CommandSessionCreate):
                    sid = cmd.data.session_id or new_session_id()
                    emitter.emit_runtime_session_created(session_id=sid)

                elif isinstance(cmd, CommandSessionDelete):
                    if store is None:
                        emitter.emit_error(
                            severity="transient",
                            message="command.session.delete requires EventStore",
                            stage="session.delete",
                        )
                    else:
                        await store.clear(cmd.data.session_id)

                elif isinstance(cmd, CommandSessionRename):
                    if store is None:
                        emitter.emit_error(
                            severity="transient",
                            message="command.session.rename requires EventStore",
                            stage="session.rename",
                        )
                    else:
                        fr, to = cmd.data.from_session_id.strip(), cmd.data.to_session_id.strip()
                        if fr and to and fr != to:
                            await store.rename_session(fr, to)
                            emitter.emit_runtime_session_renamed(from_session_id=fr, to_session_id=to)
                            ids = await store.list_session_ids()
                            emitter.emit_runtime_sessions(sessions=ids)

                elif isinstance(cmd, CommandAttachFile):
                    import base64

                    from agloom.runtime.upload import stage_attached_bytes

                    try:
                        raw = base64.b64decode(cmd.data.content_base64.strip())
                    except Exception as exc:
                        emitter.emit_error(
                            severity="transient",
                            message=f"invalid base64 attachment: {exc}",
                            stage="attach.file",
                        )
                    else:
                        try:
                            rel, nbytes = stage_attached_bytes(agent, filename=cmd.data.filename, raw=raw)
                        except Exception as exc:
                            emitter.emit_error(severity="transient", message=str(exc), stage="attach.file")
                        else:
                            emitter.emit_runtime_file_staged(path=rel, nbytes=nbytes, thread=cmd.data.thread)

                elif isinstance(cmd, CommandToolInvoke):
                    raw_sz = len(json.dumps(cmd.data.arguments, ensure_ascii=False))
                    if raw_sz > 32_000:
                        emitter.emit_runtime_tool_result(ok=False, error="arguments too large")
                    else:
                        tools = getattr(agent, "config", {}).get("tools", []) or []
                        tool = next((x for x in tools if getattr(x, "name", None) == cmd.data.name), None)
                        if tool is None:
                            emitter.emit_runtime_tool_result(ok=False, error="unknown_tool")
                        else:
                            try:
                                out = await tool.ainvoke(cmd.data.arguments)
                                emitter.emit_runtime_tool_result(ok=True, result=out)
                            except Exception as exc:
                                emitter.emit_runtime_tool_result(ok=False, error=str(exc))

                elif isinstance(cmd, CommandConfigSet):
                    try:
                        from agloom.runtime.serve_cli import parse_pattern_name
                        from agloom.unified_agent import resolve_model, resolve_system_prompt

                        data = cmd.data
                        if data.model_id:
                            agent.config["llm"] = resolve_model(data.model_id)
                        if data.temperature is not None:
                            llm = agent.config.get("llm")
                            if llm is not None and hasattr(llm, "bind"):
                                agent.config["llm"] = llm.bind(temperature=data.temperature)
                        if data.system_prompt is not None:
                            agent.config["system_prompt"] = resolve_system_prompt(data.system_prompt)
                        if data.pattern is not None:
                            agent.config["fallback_pattern"] = parse_pattern_name(data.pattern)
                    except Exception as exc:
                        emitter.emit_error(severity="transient", message=str(exc), stage="config.set")
                    else:
                        if budget_tracker is not None:
                            fs = cmd.data.model_fields_set
                            from agloom.runtime.budget_tracker import _UNSET

                            tok = (
                                cmd.data.budget_token_limit
                                if "budget_token_limit" in fs
                                and cmd.data.budget_token_limit is not None
                                and cmd.data.budget_token_limit > 0
                                else (None if "budget_token_limit" in fs else _UNSET)
                            )
                            cst = (
                                cmd.data.budget_cost_usd_limit
                                if "budget_cost_usd_limit" in fs
                                and cmd.data.budget_cost_usd_limit is not None
                                and cmd.data.budget_cost_usd_limit > 0
                                else (None if "budget_cost_usd_limit" in fs else _UNSET)
                            )
                            if tok is not _UNSET or cst is not _UNSET:
                                budget_tracker.patch_limits(token_limit=tok, cost_usd=cst)
                        from agloom.cli_tools import CLI_TOOL_NAMES

                        tool_objs = getattr(agent, "config", {}).get("tools", []) or []
                        _names = {getattr(t, "name", None) for t in tool_objs}
                        _ct_ct = sum(1 for n in _names if n in CLI_TOOL_NAMES)
                        _ct_en = _ct_ct > 0
                        llm_after = agent.config.get("llm")
                        mid_guess = getattr(llm_after, "model_name", None) or getattr(llm_after, "model", None)
                        if mid_guess is None and llm_after is not None:
                            mid_guess = type(llm_after).__name__
                        emitter.emit_runtime_config_applied(
                            model_id=str(mid_guess) if mid_guess else (cmd.data.model_id or None),
                            cli_tools_enabled=_ct_en,
                            cli_tools_count=_ct_ct,
                        )
                        tools_after = agent.config.get("tools", []) or []
                        emitter.emit_runtime_config(
                            model_id=str(mid_guess) if mid_guess else (cmd.data.model_id or ""),
                            tool_names=[getattr(t, "name", str(t)) for t in tools_after],
                            cli_tools_enabled=_ct_en,
                            cli_tools_count=_ct_ct,
                        )

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
            stop_hb.set()
            if hb_task is not None:
                hb_task.cancel()
                try:
                    await hb_task
                except (asyncio.CancelledError, Exception):
                    pass
            for t in list(_tasks.values()):
                if not t.done():
                    hitl_bridge.prepare_invocation_cancel(t, reason="shutdown")
                    t.cancel()
            if _tasks:
                await asyncio.gather(*_tasks.values(), return_exceptions=True)
            emitter.close()
