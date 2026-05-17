"""Shared AGP command dispatch for stdio and WebSocket runtimes."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..mcp_support import MCPConnectionError
from ..protocol import SessionEmitter
from ..protocol.commands import (
    CommandAttachFile,
    CommandCancel,
    CommandConfigSet,
    CommandFeedback,
    CommandHarnessGit,
    CommandHITLRespond,
    CommandInvoke,
    CommandMemoryClear,
    CommandMemoryPopLastTurn,
    CommandPing,
    CommandPlanPreview,
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
from .bridge import new_session_id, run_invocation
from .hitl import HITLBridge

_logger = logging.getLogger(__name__)

_TOOL_INVOKE_ARG_LIMIT = 32_000


def _json_payload_over_limit(obj: Any, *, limit: int) -> bool:
    """Estimate serialized JSON size without building the full string first."""
    if obj is None:
        return False

    def walk(value: Any, depth: int) -> int:
        if depth > 48:
            return limit + 1
        if value is None:
            return 4
        if isinstance(value, bool):
            return 4 if value else 5
        if isinstance(value, (int, float)):
            return len(repr(value))
        if isinstance(value, str):
            return len(value) + 2
        if isinstance(value, dict):
            total = 2
            for k, v in value.items():
                total += len(str(k)) + 4 + walk(v, depth + 1)
                if total > limit:
                    return total
            return total
        if isinstance(value, (list, tuple)):
            total = 2
            for item in value:
                total += walk(item, depth + 1) + 1
                if total > limit:
                    return total
            return total
        return len(json.dumps(value, ensure_ascii=False, default=str))

    return walk(obj, 0) > limit


def runtime_log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def runtime_cli_tool_metrics(agent: Any) -> tuple[bool, int]:
    from ..cli_tools import CLI_TOOL_NAMES

    tool_objs = getattr(agent, "config", {}).get("tools", []) or []
    names = {getattr(t, "name", None) for t in tool_objs}
    count = sum(1 for n in names if n in CLI_TOOL_NAMES)
    return count > 0, count


class DispatchResult(str, Enum):
    CONTINUE = "continue"
    SHUTDOWN = "shutdown"


async def dispatch_command(
    cmd: Any,
    *,
    agent: Any,
    emitter: SessionEmitter,
    hitl_bridge: HITLBridge,
    ensure_agent: Any = None,
    rewrite_session_marker: Any = None,
    invocation_tasks: set[asyncio.Task[Any]],
    thread_tasks: dict[str, asyncio.Task[Any]],
    shutdown: asyncio.Event,
    store: Any = None,
    session_id: str = "",
    budget_tracker: Any | None = None,
    invoke_working_dir: Path | None = None,
) -> DispatchResult:
    """Route one typed command to its handler."""

    if isinstance(cmd, CommandRuntimeShutdown):
        shutdown.set()
        return DispatchResult.SHUTDOWN

    if isinstance(cmd, CommandHITLRespond):
        ok = hitl_bridge.respond(
            cmd.data.request_id,
            cmd.data.decision,
            text=cmd.data.text,
            actor=cmd.data.actor,
        )
        if not ok:
            runtime_log(f"[agloom-runtime] no pending HITL request for id={cmd.data.request_id!r}")
        return DispatchResult.CONTINUE

    async def _agent_or_skip(*, emit_on_missing: bool = True) -> Any | None:
        if agent is not None:
            return agent
        if ensure_agent is not None:
            try:
                return await ensure_agent()
            except ImportError:
                return None
            except MCPConnectionError:
                raise
            except RuntimeError:
                return None
        if emit_on_missing:
            emitter.emit_error(severity="transient", message="agent not available — no model configured", stage="invoke")
        return None

    if isinstance(cmd, CommandInvoke):
        resolved = await _agent_or_skip()
        if resolved is None:
            runtime_log(
                "[agloom-runtime] command.invoke skipped — agent did not start. "
                "Typical causes: missing provider API key (e.g. NVIDIA_API_KEY for nvidia:… models), "
                "invalid or unresolved --model, or missing optional extras. "
                "See stderr for earlier bootstrap errors; use an up-to-date agloom-cli so direct mode "
                "prints AGP error.* lines on stderr."
            )
            emitter.emit_error(
                severity="transient",
                message=(
                    "Invoke skipped — the agent never started (missing API keys, unresolved model, or extras). "
                    "Check this terminal for [agloom-runtime] lines."
                ),
                stage="invoke.skipped",
            )
            return DispatchResult.CONTINUE

        invoke_agent: Any = resolved
        if budget_tracker is not None:
            if not await budget_tracker.reserve_invoke_slot():
                emitter.emit_error(
                    severity="transient",
                    message="Session budget exhausted (tokens or cost). Raise limits via command.config.set.",
                    stage="budget.blocked",
                )
                return DispatchResult.CONTINUE

        from .attachment_stage import prepare_invoke_command

        thread = cmd.data.thread or f"thread_{uuid4().hex[:16]}"
        existing = thread_tasks.get(thread)
        if existing is not None and not existing.done():
            emitter.emit_error(
                severity="transient",
                message=f"command.invoke already running for thread {thread!r}",
                stage="invoke.concurrent",
            )
            return DispatchResult.CONTINUE

        wd = invoke_working_dir or Path.cwd().resolve()
        try:
            prompt, summaries = prepare_invoke_command(cmd, agent=invoke_agent, thread=thread, working_dir=wd)
        except ValueError as exc:
            emitter.emit_error(severity="transient", message=str(exc), stage="invoke.attachments")
            return DispatchResult.CONTINUE

        inv_emitter = emitter.fork_for_thread(thread)

        async def _bound_invoke() -> None:
            cur = asyncio.current_task()
            if cur is not None:
                hitl_bridge.bind_task_emitter(cur, inv_emitter, thread=thread)
            await run_invocation(
                agent=invoke_agent,
                prompt=prompt,
                thread=thread,
                emitter=inv_emitter,
                hitl_bridge=hitl_bridge,
                user_attachments=summaries or None,
            )

        task = asyncio.create_task(_bound_invoke(), name=f"agp-invocation-{thread[:8]}")
        invocation_tasks.add(task)
        thread_tasks[thread] = task

        def _on_done_invocation(t: asyncio.Task[Any]) -> None:
            invocation_tasks.discard(t)
            thread_tasks.pop(thread, None)

        task.add_done_callback(_on_done_invocation)
        return DispatchResult.CONTINUE

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
            # No specific thread — cancel everything (WS may only track thread_tasks)
            seen: set[asyncio.Task[Any]] = set(invocation_tasks)
            seen.update(thread_tasks.values())
            for t in seen:
                if not t.done():
                    hitl_bridge.prepare_invocation_cancel(t, reason="user_aborted")
                    t.cancel()
                    cancelled_n += 1
            hitl_bridge.cancel_all()
        if not cancelled_n:
            runtime_log(
                f"[agloom-runtime] command.cancel matched no invocations"
                f"{f' (thread={target_thread!r})' if target_thread else ''}"
            )
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandWorkerAssign):
        worker_agent = await _agent_or_skip()
        if worker_agent is None:
            return DispatchResult.CONTINUE

        wthread = cmd.data.thread or f"wt_{uuid4().hex[:12]}"
        existing_w = thread_tasks.get(wthread)
        if existing_w is not None and not existing_w.done():
            emitter.emit_error(
                severity="transient",
                message=f"command.worker.assign already running for thread {wthread!r}",
                stage="worker.concurrent",
            )
            return DispatchResult.CONTINUE

        w_emitter = emitter.fork_for_thread(wthread)
        # Emit worker.spawned so the supervisor sees the task has been dispatched.
        w_emitter.emit_worker_spawned(
            worker_id=cmd.data.worker_id,
            name=cmd.data.worker_id,
            pattern=cmd.data.pattern,
            task=cmd.data.task,
        )

        async def _bound_worker() -> None:
            cur = asyncio.current_task()
            if cur is not None:
                hitl_bridge.bind_task_emitter(cur, w_emitter, thread=wthread)
            await run_invocation(
                agent=worker_agent,
                prompt=cmd.data.task,
                thread=wthread,
                emitter=w_emitter,
                hitl_bridge=hitl_bridge,
            )

        wtask = asyncio.create_task(
            _bound_worker(),
            name=f"agp-worker-{cmd.data.worker_id[:8]}",
        )
        invocation_tasks.add(wtask)
        thread_tasks[wthread] = wtask

        def _on_done_worker(t: asyncio.Task[Any]) -> None:
            invocation_tasks.discard(t)
            thread_tasks.pop(wthread, None)

        wtask.add_done_callback(_on_done_worker)
        runtime_log(f"[agloom-runtime] worker {cmd.data.worker_id!r} dispatched on thread={wthread!r}")
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandSessionResume):
        from_seq = max(0, cmd.data.from_seq or 0)
        if store is not None:
            emitter.resume(resumed_from_thread=cmd.data.thread, replayed_from_seq=from_seq if from_seq > 0 else None)
            async for evt_dict in store.replay(session_id, from_seq=from_seq):
                emitter.write_replay_dict(evt_dict)
        else:
            emitter.resume(resumed_from_thread=cmd.data.thread)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandFeedback):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        feedback_handler = getattr(agent, "config", {}).get("feedback_handler")
        if feedback_handler is None:
            runtime_log("[agloom-runtime] command.feedback received but no feedback_handler configured")
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
                runtime_log(f"[agloom-runtime] feedback handler error: {exc!r}")
        # Always emit the wire event so frontends can track it regardless.
        emitter.emit_feedback_scored(
            run_id=cmd.data.run_id,
            rating=cmd.data.rating,
            comment=cmd.data.comment,
            correct=cmd.data.correct,
            metadata=cmd.data.metadata,
        )
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandSnapshotRequest):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        checkpointer = getattr(agent, "config", {}).get("checkpointer")
        label = cmd.data.label
        thread = cmd.data.thread or session_id
        if checkpointer is None:
            runtime_log("[agloom-runtime] command.snapshot.request: no checkpointer configured")
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
                runtime_log(f"[agloom-runtime] snapshot failed: {exc!r}")
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandPing):
        emitter.emit_runtime_pong(ping_id=cmd.data.ping_id)
        return DispatchResult.CONTINUE

    if isinstance(cmd, CommandSchemaRequest):
        from ..protocol.schema import build_schema

        emitter.emit_runtime_schema(json_schema=build_schema())
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandProvidersList):
        from agloom.llm.provider_registry import provider_catalog

        emitter.emit_runtime_providers(providers=provider_catalog())
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandToolList):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        tools = getattr(agent, "config", {}).get("tools", []) or []
        rows: list[tuple[str, str | None]] = []
        for t in tools:
            nm = getattr(t, "name", "?")
            desc = getattr(t, "description", None)
            rows.append((nm, str(desc) if desc else None))
        emitter.emit_runtime_tools(tools=rows)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandSubscribe):
        emitter.set_subscription_prefixes(cmd.data.prefixes if cmd.data.prefixes else None)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandUnsubscribe):
        emitter.clear_subscription()
        return DispatchResult.CONTINUE


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
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandSessionCreate):
        sid = cmd.data.session_id or new_session_id()
        emitter.emit_runtime_session_created(session_id=sid)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandSessionDelete):
        if store is None:
            emitter.emit_error(
                severity="transient",
                message="command.session.delete requires --store",
                stage="session.delete",
            )
        else:
            target = cmd.data.session_id.strip()
            if target != session_id:
                emitter.emit_error(
                    severity="transient",
                    message=f"command.session.delete refused: session_id {target!r} does not match active session {session_id!r}",
                    stage="session.delete",
                )
            else:
                await store.clear(target)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandSessionRename):
        if store is None:
            emitter.emit_error(
                severity="transient",
                message="command.session.rename requires --store",
                stage="session.rename",
            )
        else:
            fr, to = cmd.data.from_session_id.strip(), cmd.data.to_session_id.strip()
            if fr != session_id:
                emitter.emit_error(
                    severity="transient",
                    message=(
                        f"command.session.rename refused: from_session_id {fr!r} "
                        f"does not match active session {session_id!r}"
                    ),
                    stage="session.rename",
                )
            elif fr and to and fr != to:
                await store.rename_session(fr, to)
                emitter.emit_runtime_session_renamed(from_session_id=fr, to_session_id=to)
                ids = await store.list_session_ids()
                emitter.emit_runtime_sessions(sessions=ids)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandAttachFile):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        import base64

        from .upload import stage_attached_bytes

        try:
            raw = base64.b64decode(cmd.data.content_base64.strip())
        except Exception as exc:
            emitter.emit_error(
                severity="transient",
                message=f"invalid base64 attachment: {exc}",
                stage="attach.file",
            )
            return DispatchResult.CONTINUE

        try:
            rel, nbytes = stage_attached_bytes(agent, filename=cmd.data.filename, raw=raw)
        except Exception as exc:
            emitter.emit_error(severity="transient", message=str(exc), stage="attach.file")
            return DispatchResult.CONTINUE

        emitter.emit_runtime_file_staged(path=rel, nbytes=nbytes, thread=cmd.data.thread)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandToolInvoke):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        if _json_payload_over_limit(cmd.data.arguments, limit=32_000):
            emitter.emit_runtime_tool_result(ok=False, error="arguments too large")
            return DispatchResult.CONTINUE

        tools = getattr(agent, "config", {}).get("tools", []) or []
        tool = next((x for x in tools if getattr(x, "name", None) == cmd.data.name), None)
        if tool is None:
            emitter.emit_runtime_tool_result(ok=False, error="unknown_tool")
            return DispatchResult.CONTINUE

        try:
            out = await tool.ainvoke(cmd.data.arguments)
            emitter.emit_runtime_tool_result(ok=True, result=out)
        except Exception as exc:
            emitter.emit_runtime_tool_result(ok=False, error=str(exc))
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandConfigSet):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        try:
            from agloom.unified_agent import resolve_model, resolve_system_prompt

            data = cmd.data
            if data.model_id:
                agent.config["llm"] = resolve_model(data.model_id)
            bind_kw: dict[str, Any] = {}
            if data.temperature is not None:
                bind_kw["temperature"] = data.temperature
            if data.top_p is not None:
                bind_kw["top_p"] = data.top_p
            if bind_kw:
                llm = agent.config.get("llm")
                if llm is not None and hasattr(llm, "bind"):
                    agent.config["llm"] = llm.bind(**bind_kw)
            if data.system_prompt is not None:
                agent.config["system_prompt"] = resolve_system_prompt(data.system_prompt)
        except Exception as exc:
            emitter.emit_error(severity="transient", message=str(exc), stage="config.set")
            return DispatchResult.CONTINUE

        if budget_tracker is not None:
            fs = cmd.data.model_fields_set
            if "budget_token_limit" in fs or "budget_cost_usd_limit" in fs:
                from ..runtime.budget_tracker import _UNSET

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
                budget_tracker.patch_limits(token_limit=tok, cost_usd=cst)
        _cta, _ctb = runtime_cli_tool_metrics(agent)
        llm_after = agent.config.get("llm")
        mid_guess = getattr(llm_after, "model_name", None) or getattr(llm_after, "model", None)
        if mid_guess is None and llm_after is not None:
            mid_guess = type(llm_after).__name__
        emitter.emit_runtime_config_applied(
            model_id=str(mid_guess) if mid_guess else (cmd.data.model_id or None),
            cli_tools_enabled=_cta,
            cli_tools_count=_ctb,
        )
        tools_after = agent.config.get("tools", []) or []
        emitter.emit_runtime_config(
            model_id=str(mid_guess) if mid_guess else (cmd.data.model_id or ""),
            tool_names=[getattr(t, "name", str(t)) for t in tools_after],
            cli_tools_enabled=_cta,
            cli_tools_count=_ctb,
        )
        # Update session marker when model changes mid-session
        if cmd.data.model_id is not None and rewrite_session_marker is not None:
            rewrite_session_marker(str(mid_guess) if mid_guess else cmd.data.model_id)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandMemoryClear):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        mem = agent.config.get("memory")
        if mem is None:
            emitter.emit_error(
                severity="transient",
                message="agent has no session memory configured",
                stage="memory.clear",
            )
            return DispatchResult.CONTINUE

        target = cmd.data.thread or getattr(emitter, "_thread", None)
        if not target:
            emitter.emit_error(
                severity="transient",
                message="command.memory.clear requires data.thread",
                stage="memory.clear",
            )
            return DispatchResult.CONTINUE

        try:
            await mem.aclear_thread(str(target))
        except Exception as exc:
            emitter.emit_error(severity="transient", message=str(exc), stage="memory.clear")
            return DispatchResult.CONTINUE

        fork = emitter.fork_for_thread(str(target))
        fork.emit_memory_session_cleared(thread=str(target))
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandMemoryPopLastTurn):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        mem = agent.config.get("memory")
        if mem is None:
            emitter.emit_error(
                severity="transient",
                message="agent has no session memory configured",
                stage="memory.pop_last_turn",
            )
            return DispatchResult.CONTINUE

        target = cmd.data.thread or getattr(emitter, "_thread", None)
        if not target:
            emitter.emit_error(
                severity="transient",
                message="command.memory.pop_last_turn requires data.thread",
                stage="memory.pop_last_turn",
            )
            return DispatchResult.CONTINUE

        try:
            remaining = await mem.apop_last_turn(str(target))
        except Exception as exc:
            emitter.emit_error(severity="transient", message=str(exc), stage="memory.pop_last_turn")
            return DispatchResult.CONTINUE

        if remaining is None:
            emitter.emit_error(
                severity="transient",
                message="nothing to undo (no session turns for this thread)",
                stage="memory.pop_last_turn",
            )
            return DispatchResult.CONTINUE

        fork = emitter.fork_for_thread(str(target))
        fork.emit_memory_session_turn_popped(thread=str(target), remaining_turns=remaining)
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandHarnessGit):
        agent = await _agent_or_skip()
        if agent is None:
            return DispatchResult.CONTINUE

        gs = agent.config.get("_git_session")
        if gs is None:
            emitter.emit_runtime_tool_result(
                ok=False,
                error="harness/git unavailable (requires agent store + harness — omit --no-harness)",
            )
            return DispatchResult.CONTINUE

        op = cmd.data.op
        try:
            if op == "checkpoint":
                sid = str(getattr(emitter, "_session", "") or "")
                tag_name = await gs.checkpoint(cmd.data.name or "cli", cmd.data.description or "", sid)
                text = f"Checkpoint tag: {tag_name}" if tag_name else "Checkpoint failed"
                emitter.emit_runtime_tool_result(ok=bool(tag_name), result=text)
            elif op == "diff":
                diff_text = await gs.diff_unified(path=cmd.data.path or "", cached=cmd.data.cached)
                emitter.emit_runtime_tool_result(ok=True, result=diff_text)
            elif op == "status":
                st = await gs.status()
                if not st.is_repo:
                    emitter.emit_runtime_tool_result(ok=True, result="Not a git repository.")
                else:
                    parts = [
                        f"branch={st.branch}",
                        f"clean={st.clean}",
                        f"staged={len(st.staged)}",
                        f"unstaged={len(st.unstaged)}",
                        f"untracked={len(st.untracked)}",
                    ]
                    emitter.emit_runtime_tool_result(ok=True, result="\n".join(parts))
            elif op == "checkpoints":
                cps = await gs.list_checkpoints()
                lines = [f"{c.name} @ {c.commit_hash[:7]} — {c.description[:120]}" for c in cps[:30]]
                emitter.emit_runtime_tool_result(ok=True, result="\n".join(lines) if lines else "(no checkpoints)")
            elif op == "revert_hint":
                hint = await gs.get_revert_hint()
                emitter.emit_runtime_tool_result(ok=True, result=hint or "(no hint)")
            else:
                emitter.emit_runtime_tool_result(ok=False, error=f"unknown harness git op: {op!r}")
        except Exception as exc:
            emitter.emit_runtime_tool_result(ok=False, error=str(exc))
        return DispatchResult.CONTINUE


    if isinstance(cmd, CommandPlanPreview):
        prompt = (cmd.data.prompt or "").strip()
        if not prompt:
            emitter.emit_error(
                severity="transient",
                message="command.plan.preview requires a non-empty prompt",
                stage="plan.preview",
            )
            return DispatchResult.CONTINUE

        resolved = await _agent_or_skip(emit_on_missing=False)
        if resolved is None:
            emitter.emit_error(
                severity="transient",
                message=(
                    "plan.preview requires a running agent (model + credentials). "
                    "Bootstrap the session first; if the agent never started, check API keys and model flags."
                ),
                stage="plan.preview",
            )
            return DispatchResult.CONTINUE

        cfg = getattr(resolved, "config", None)
        if not isinstance(cfg, dict):
            emitter.emit_error(
                severity="transient",
                message="agent is missing a config dict (cannot run plan preview)",
                stage="plan.preview",
            )
            return DispatchResult.CONTINUE

        llm = cfg.get("llm")
        if llm is None:
            emitter.emit_error(severity="transient", message="no LLM configured", stage="plan.preview")
            return DispatchResult.CONTINUE

        from agloom.classifier import analyze_query

        try:
            analysis = await analyze_query(
                llm,
                prompt,
                cfg.get("tools") or [],
                skill_context="",
                classifier_timeout=float(cfg.get("classifier_timeout", 60.0)),
                structured_max_retries=int(cfg.get("structured_max_retries", 2)),
                fallback_pattern=cfg.get("fallback_pattern"),
            )
            steps: list[str] = []
            for i, st in enumerate(analysis.subtasks):
                steps.append(f"{i + 1}. [{st.worker_id}] {st.task}")
            if not steps:
                steps.append(f"1. Run as {analysis.pattern.value} (no worker subtasks returned).")
            emitter.emit_plan_preview(
                pattern=analysis.pattern.value,
                complexity=analysis.complexity,
                reasoning=(analysis.reasoning or ""),
                steps=steps,
            )
        except Exception as exc:
            emitter.emit_error(severity="transient", message=str(exc), stage="plan.preview")
        return DispatchResult.CONTINUE


    runtime_log(f"[agloom-runtime] unsupported command type: {type(cmd).__name__!r}")
    return DispatchResult.CONTINUE


__all__ = ["DispatchResult", "dispatch_command", "runtime_cli_tool_metrics", "runtime_log"]
