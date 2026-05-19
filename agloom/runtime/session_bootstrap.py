"""Shared runtime session setup and teardown for stdio and WebSocket transports."""

from __future__ import annotations

import asyncio
import logging
from argparse import Namespace
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..protocol import SessionEmitter
from ..protocol.store import EventStore
from .bridge import new_session_id
from .hitl import HITLBridge, InvocationCancelReason
from .hitl_allowlist import (
    HitlAllowlistPolicy,
    build_session_hitl_coalescer,
    hitl_allowlist_paths_for_runtime,
)
from .serve_cli import (
    inject_api_key_secret_from_session_marker,
    merge_api_key_env_from_session_marker,
    merge_base_url_from_session_marker,
    merge_ws_connection_args,
    session_started_snapshot_from_args,
)
from .workspace_bootstrap import (
    bootstrap_optional_agsuperbrain,
    ensure_agloom_workspace,
    session_marker_json_path,
    write_session_started_json,
)

_logger = logging.getLogger(__name__)

INVOCATION_JOIN_TIMEOUT_S = 600.0


@dataclass
class PreparedRuntimeSession:
    """Workspace + marker state shared by stdio and WebSocket session loops."""

    session_id: str
    initial_thread: str
    cwd: Path
    sessions_dir: Path
    marker_path: Path | None
    working_args: Namespace
    allowlist: HitlAllowlistPolicy
    coalescer: Any
    allowlist_persist_path: str | None
    allowlist_session_marker: Path | None = None
    yaml_created: bool = False


def prepare_runtime_session(
    args: Namespace,
    *,
    transport: str,
    session_id: str | None = None,
    initial_thread: str | None = None,
    cwd: Path | None = None,
    ws_path_query: str = "",
) -> PreparedRuntimeSession:
    """Ensure workspace, merge WS query overrides, write session marker JSON."""
    root = (cwd or Path.cwd()).resolve()
    working_args = merge_ws_connection_args(args, ws_path_query) if ws_path_query else args
    sessions_dir, yaml_created = ensure_agloom_workspace(root, args=working_args)
    bootstrap_optional_agsuperbrain(root, args=working_args)

    sid = session_id or new_session_id()
    thread = (initial_thread or "").strip() or (
        f"thread_{uuid4().hex[:16]}" if transport == "stdio" else f"t_{uuid4().hex[:12]}"
    )
    marker_path = session_marker_json_path(sessions_dir, sid) if sessions_dir.is_dir() else None

    inject_api_key_secret_from_session_marker(working_args, marker_path)
    merge_api_key_env_from_session_marker(working_args, marker_path)
    merge_base_url_from_session_marker(working_args, marker_path)

    allowlist, persist_path, session_marker = hitl_allowlist_paths_for_runtime(
        working_args,
        session_marker_json=marker_path,
        session_scoped=marker_path is not None,
        cwd=root,
    )
    coalescer = build_session_hitl_coalescer(session_marker)

    write_session_started_json(
        sessions_dir,
        sid,
        transport=transport,
        thread=thread,
        record_cwd=root,
        hitl_tool_allowlist=sorted(allowlist.global_tools()),
        extra=session_started_snapshot_from_args(working_args),
    )

    return PreparedRuntimeSession(
        session_id=sid,
        initial_thread=thread,
        cwd=root,
        sessions_dir=sessions_dir,
        marker_path=marker_path,
        working_args=working_args,
        allowlist=allowlist,
        coalescer=coalescer,
        allowlist_persist_path=str(persist_path) if persist_path is not None else None,
        allowlist_session_marker=session_marker,
        yaml_created=yaml_created,
    )


def make_hitl_bridge(emitter: SessionEmitter, prepared: PreparedRuntimeSession) -> HITLBridge:
    return HITLBridge(
        emitter,
        tool_allowlist=prepared.allowlist,
        allowlist_persist_path=prepared.allowlist_persist_path,
        allowlist_session_marker=prepared.allowlist_session_marker,
    )


def _agent_config_dict(agent: Any) -> dict[str, Any]:
    """``UnifiedAgent`` or bare ``create_agent`` config dict."""
    if isinstance(agent, dict):
        return agent
    inner = getattr(agent, "config", None)
    return inner if isinstance(inner, dict) else {}


def emit_agent_tool_catalog(
    emitter: SessionEmitter,
    agent: Any,
    *,
    model_id: str | None = None,
) -> None:
    """Emit ``runtime.config`` + ``runtime.tools`` with the agent's full tool list (includes MCP after connect)."""
    from agloom.cli_tools import CLI_TOOL_NAMES

    cfg = _agent_config_dict(agent)
    tool_objs = cfg.get("tools", []) or []
    tool_names = [getattr(t, "name", str(t)) for t in tool_objs]
    rows: list[tuple[str, str | None]] = []
    for t in tool_objs:
        nm = getattr(t, "name", "?")
        desc = getattr(t, "description", None)
        rows.append((nm, str(desc) if desc else None))
    names_set = {getattr(t, "name", None) for t in tool_objs}
    cli_count = sum(1 for n in names_set if n in CLI_TOOL_NAMES)
    cli_en = cli_count > 0
    mid = model_id
    if mid is None:
        llm_obj = cfg.get("llm")
        if llm_obj is not None:
            mid = getattr(llm_obj, "model_name", None) or getattr(llm_obj, "model", None)
            if mid is None:
                mid = type(llm_obj).__name__
    emitter.emit_runtime_config(
        model_id=str(mid) if mid else None,
        tool_names=tool_names,
        cli_tools_enabled=cli_en,
        cli_tools_count=cli_count,
    )
    if rows:
        emitter.emit_runtime_tools(tools=rows)


async def emit_agent_runtime_ready(
    emitter: SessionEmitter,
    agent: Any,
    *,
    agent_name: str = "agloom-runtime",
    harness_enabled: bool = False,
    sidebar: dict[str, Any] | None = None,
) -> None:
    """Emit ``runtime.ready`` + ``runtime.config`` after agent bootstrap."""
    from agloom.cli_tools import CLI_TOOL_NAMES

    tool_objs = getattr(agent, "config", {}).get("tools", []) or []
    names = {getattr(t, "name", None) for t in tool_objs}
    cli_count = sum(1 for n in names if n in CLI_TOOL_NAMES)
    cli_en = cli_count > 0
    llm_obj = getattr(agent, "config", {}).get("llm")
    model_id_guess = None
    if llm_obj is not None:
        model_id_guess = getattr(llm_obj, "model_name", None) or getattr(llm_obj, "model", None)
        if model_id_guess is None:
            model_id_guess = type(llm_obj).__name__

    ready_kw: dict[str, Any] = {
        "agent_name": str(getattr(agent, "config", {}).get("name", agent_name)),
        "cli_tools_enabled": cli_en,
        "cli_tools_count": cli_count,
    }
    if sidebar:
        ready_kw.update(sidebar)
    if harness_enabled:
        ready_kw["harness_enabled"] = True
    emitter.emit_runtime_ready(**ready_kw)
    emitter.emit_runtime_config(
        model_id=str(model_id_guess) if model_id_guess else None,
        tool_names=[getattr(t, "name", str(t)) for t in tool_objs],
        cli_tools_enabled=cli_en,
        cli_tools_count=cli_count,
    )


async def connect_mcp_or_raise(agent: Any, emitter: SessionEmitter) -> None:
    """Connect MCP servers configured on *agent*; emit fatal error and raise on failure."""
    if not agent.config.get("_mcp_servers"):
        return
    from agloom.unified_agent import _ensure_mcp_connected

    try:
        await _ensure_mcp_connected(agent.config)
    except Exception as exc:
        msg = str(exc).strip() or repr(exc)
        emitter.emit_error(
            severity="fatal",
            message=msg,
            stage="mcp.bootstrap",
            error_class=type(exc).__name__,
        )
        raise

    rows = agent.config.get("_mcp_server_rows") or []
    if rows:
        emitter.emit_runtime_mcp_servers(
            server_names=[str(r.get("name") or "") for r in rows],
            servers=rows,
        )
    emit_agent_tool_catalog(emitter, agent)


async def cancel_runtime_invocations(
    *,
    hitl_bridge: HITLBridge,
    thread_tasks: dict[str, asyncio.Task[None]],
    invocation_tasks: set[asyncio.Task[None]] | None = None,
    reason: str = "shutdown",
    join_timeout_s: float = INVOCATION_JOIN_TIMEOUT_S,
) -> None:
    """Cancel in-flight invokes/workers and drain HITL waiters."""
    seen: set[asyncio.Task[None]] = set()
    if invocation_tasks:
        seen.update(invocation_tasks)
    seen.update(thread_tasks.values())

    inv_reason: InvocationCancelReason = (
        "user_aborted" if reason == "user_aborted" else "shutdown"
    )
    for task in seen:
        if not task.done():
            hitl_bridge.prepare_invocation_cancel(task, reason=inv_reason)
            task.cancel()

    if seen:
        await asyncio.gather(
            *[asyncio.wait_for(asyncio.shield(t), timeout=join_timeout_s) for t in seen],
            return_exceptions=True,
        )
    hitl_bridge.cancel_all()


async def teardown_runtime_session(
    *,
    agent: Any | None,
    emitter: Any,
    hitl_bridge: HITLBridge,
    thread_tasks: dict[str, asyncio.Task[None]],
    invocation_tasks: set[asyncio.Task[None]] | None = None,
    mem_cleanups: list[Callable[[], Awaitable[None]]] | None = None,
    stop_heartbeat: asyncio.Event | None = None,
    heartbeat_task: asyncio.Task[None] | None = None,
    close_reason: str = "shutdown",
    lg_store_cleanup: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Idempotent session shutdown: heartbeat, tasks, emitter, agent, memory, LT store."""
    if stop_heartbeat is not None:
        stop_heartbeat.set()
    if heartbeat_task is not None and not heartbeat_task.done():
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except (asyncio.CancelledError, Exception):
            pass

    await cancel_runtime_invocations(
        hitl_bridge=hitl_bridge,
        thread_tasks=thread_tasks,
        invocation_tasks=invocation_tasks,
        reason=close_reason,
    )

    if getattr(emitter, "is_open", False):
        try:
            emitter.close(reason=close_reason)
        except Exception:
            _logger.debug("emitter.close failed during teardown", exc_info=True)

    if agent is not None:
        try:
            await agent.aclose()
        except Exception:
            _logger.debug("agent.aclose failed during teardown", exc_info=True)

    for fn in mem_cleanups or []:
        try:
            await fn()
        except Exception:
            _logger.debug("session memory cleanup failed", exc_info=True)

    if lg_store_cleanup is not None:
        try:
            await lg_store_cleanup()
        except Exception:
            _logger.debug("langgraph store cleanup failed", exc_info=True)


async def open_event_store_from_args(args: Namespace) -> EventStore | None:
    if getattr(args, "store", None) == "sqlite":
        from ..protocol.store import SqliteEventStore

        return SqliteEventStore(getattr(args, "store_path", None) or ".agloom/agp_events.db")
    if getattr(args, "store", None) == "memory":
        from ..protocol.store import MemoryEventStore

        return MemoryEventStore()
    return None


__all__ = [
    "PreparedRuntimeSession",
    "cancel_runtime_invocations",
    "connect_mcp_or_raise",
    "emit_agent_tool_catalog",
    "emit_agent_runtime_ready",
    "make_hitl_bridge",
    "open_event_store_from_args",
    "prepare_runtime_session",
    "teardown_runtime_session",
]
