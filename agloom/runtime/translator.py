"""Translate :class:`agloom.AgentEvent` instances into AGP envelopes.

Maps well-known event types to the matching :class:`~agloom.protocol.SessionEmitter`
``emit_*`` helpers. Anything not handled explicitly is forwarded as ``thinking.step`` so the
wire stream stays a complete trace without silently dropping data.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from ..logging_utils import get_logger
from ..models import AgentEvent
from ..protocol import SessionEmitter
from ..protocol.emitter import _lit_token_role

logger = get_logger(__name__)

_TRANSLATOR_VERBOSE_THINKING = os.environ.get("AGLOOM_TRANSLATOR_VERBOSE_THINKING", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Event-type strings from ``UnifiedAgent.astream_events`` (opaque to callers). New types get a
# dedicated branch when needed; unknown names still flow through as ``thinking.step``.
_AGENT_EVENT_THINKING_TYPES: frozenset[str] = frozenset(
    {
        "thinking",
        "classify",
        "reflection",
        "fallback",
        "cache_hit",
    }
)

# Explicit branches in ``translate`` — used only to log when a new type falls through.
_TRANSLATED_AGENT_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "classify",
        "token",
        "done",
        "answer",
        "message_assistant",
        "tool_call",
        "tool_result",
        "graph_node_enter",
        "graph_node_exit",
        "skill_context",
        "progress",
        "skill_learned",
        "memory_lt_recall",
        "memory_session_write",
        "memory_lt_store",
        "checkpoint_saved",
        "checkpoint_restored",
        "feedback_scored",
        "worker_start",
        "worker_end",
        "llm_call",
        "orchestration",
        "runtime.mcp.servers",
        "error",
    }
) | _AGENT_EVENT_THINKING_TYPES


def _pattern_tail_upper(v: Any) -> str:
    """Normalize ``PatternType.DIRECT`` / ``"DIRECT"`` / enum dumps to ``DIRECT``."""
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    return s.split(".")[-1].upper()


def _assistant_body_from_done_result(res: dict[str, Any]) -> str:
    """Recover user-visible assistant text from ``ExecutionResult.model_dump()`` (wire-safe dict)."""
    raw = res.get("output")
    if isinstance(raw, str):
        t = raw.strip()
    elif raw is not None:
        t = str(raw).strip()
    else:
        t = ""
    if t:
        return t
    for st in res.get("steps") or []:
        if not isinstance(st, dict):
            continue
        if st.get("name") != "direct_shortcircuit":
            continue
        out = st.get("output")
        if isinstance(out, str) and out.strip():
            return out.strip()
        if out is not None and str(out).strip():
            return str(out).strip()
    return ""


def _event_thread_id(data: dict[str, Any]) -> str | None:
    for key in ("thread", "thread_id"):
        raw = data.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


def _reject_cross_thread_event(data: dict[str, Any], emitter: SessionEmitter) -> bool:
    """Drop events tagged for a different LangGraph thread than this emitter fork."""
    tagged = _event_thread_id(data)
    if tagged is None:
        return False
    return tagged != emitter._thread


def _new_tool_call_id(tool: str) -> str:
    return f"tc_{tool}_{uuid4().hex[:12]}"


def _result_execution_failed(res: dict[str, Any]) -> bool:
    """True when wire ``ExecutionResult`` explicitly reports ``success: false``."""
    return res.get("success") is False


def _failure_message_from_result(res: dict[str, Any]) -> str:
    err = _str(res.get("error"))
    if err:
        return err
    out = _str(res.get("output"))
    if out:
        return out
    return "execution failed"


def translate(event: AgentEvent, emitter: SessionEmitter) -> str | None:
    """Dispatch one :class:`AgentEvent` to the correct AGP emit method.

    Pure, side-effect-only-via-emitter. Unknown event types are forwarded as ``thinking.step``
    so the wire stream remains a faithful trace.

    Returns a failure message when the event should end the invocation as ``session.closed``
    with ``reason="error"`` (``AgentEvent`` ``error``, or ``done`` with ``result.success`` false).
    """
    et = event.type
    data = event.data or {}
    if _reject_cross_thread_event(data, emitter):
        return

    if et == "classify":
        # Classification events from analyze_query: payload includes pattern + complexity.
        pattern = _str(data.get("pattern")) or "UNKNOWN"
        reason = _str(data.get("reason"))
        emitter.emit_pattern_classified(
            pattern=pattern,
            complexity=_int(data.get("complexity")),
            confidence=_float(data.get("confidence")),
            reason=reason or None,
        )
        # Trace pane: routing rationale only — not the full classifier blob (subtasks belong in observability).
        emitter.emit_thinking_step(
            step="analyze_query",
            label=f"Routing · {pattern}",
            detail=reason or None,
            elapsed_ms=_int(data.get("duration_ms")),
        )
        return

    if et == "token":
        # Use raw value (not ``_str``) — token deltas MUST preserve leading/trailing whitespace
        # or the rendered stream loses word boundaries.
        # Production code (unified_agent.py, worker.py, patterns/react.py) uses "content";
        # keep "output" and "text" as legacy fallbacks. Treat empty string like absent so
        # ``{"output": "", "content": "hi"}`` does not suppress ``content``.
        raw: Any = None
        for key in ("output", "text", "content"):
            v = data.get(key)
            if v is None:
                continue
            if isinstance(v, str) and v == "":
                continue
            raw = v
            break
        if raw is None:
            return
        text = raw if isinstance(raw, str) else str(raw)
        if not text:  # skip truly empty deltas — but keep ``" "`` etc.
            return
        emitter.emit_token_delta(
            text=text,
            role=_lit_token_role(_str(data.get("role")) or "assistant"),
            message_id=_str(data.get("message_id")),
        )
        return

    if et == "done":
        # ``astream_events`` ends with ``{"result": ExecutionResult.model_dump()}`` — older tests
        # used top-level ``output``. REACT often streams prose via ``token`` first; a duplicate
        # *top-level* ``output``/``content`` on ``done`` would replay the same text in
        # ``message.assistant``. Suppress only that explicit echo — keep body recovered solely from
        # ``result`` when there was no top-level terminal field (otherwise UIs see a blank reply).
        # Tradeoff: if ``token`` deltas already streamed the same prose as ``result.output``,
        # ``message.assistant`` may repeat it once on non-DIRECT patterns; we prefer that
        # over an empty reply. Suppressing ``from_explicit`` when ``patt != DIRECT`` avoids a
        # second full copy from the done payload on top of streamed tokens.
        res = data.get("result")
        from_explicit = _str(data.get("output")) or _str(data.get("content")) or ""
        content = from_explicit
        if not content and isinstance(res, dict):
            content = _assistant_body_from_done_result(res) or ""
        patt = ""
        if isinstance(res, dict):
            patt = _pattern_tail_upper(res.get("pattern_used"))
            if not patt and isinstance(res.get("analysis"), dict):
                patt = _pattern_tail_upper((res.get("analysis") or {}).get("pattern"))
        if from_explicit and patt and patt != "DIRECT":
            content = ""
        run_id = _str(data.get("run_id"))
        pattern = _str(data.get("pattern"))
        if isinstance(res, dict):
            if not run_id:
                run_id = _str(res.get("run_id")) or run_id
            if not pattern:
                pattern = _pattern_tail_upper(res.get("pattern_used")) or pattern
                if not pattern and isinstance(res.get("analysis"), dict):
                    pattern = _str((res.get("analysis") or {}).get("pattern")) or pattern
        emitter.emit_message_assistant(
            content=content,
            message_id=_str(data.get("message_id")),
            run_id=run_id or None,
            pattern=pattern or None,
        )
        if isinstance(res, dict) and _result_execution_failed(res):
            msg = _failure_message_from_result(res)
            emitter.emit_error(
                severity="fatal",
                message=msg,
                stage=pattern or patt or "execution",
                retryable=False,
            )
            return msg
        return

    if et in ("answer", "message_assistant"):
        content = _str(data.get("output")) or _str(data.get("content")) or ""
        emitter.emit_message_assistant(
            content=content,
            message_id=_str(data.get("message_id")),
            run_id=_str(data.get("run_id")),
            pattern=_str(data.get("pattern")),
        )
        return

    if et == "tool_call":
        # Tool dispatch — translator MUST emit ``tool.call.start`` so consumers can render a
        # pending tool row. ``tool_call_id`` is mandatory on the AGP side; synthesize from name
        # when the runtime didn't supply one (older backends, unit tests).
        tool = _str(data.get("name")) or _str(data.get("tool")) or "unknown_tool"
        tcid = _str(data.get("tool_call_id")) or _str(data.get("id")) or _new_tool_call_id(tool)
        args = data.get("args")
        if not isinstance(args, dict):
            args = {}
        emitter.emit_tool_call_start(
            tool=tool,
            tool_call_id=tcid,
            args=args,
            worker=_str(data.get("worker")) or _str(data.get("worker_id")),
        )
        emitter.emit_message_tool(tool_name=tool, phase="start", detail="dispatched", call_id=tcid)
        return

    if et == "tool_result":
        tool = _str(data.get("name")) or _str(data.get("tool")) or "unknown_tool"
        tcid = _str(data.get("tool_call_id")) or _str(data.get("id")) or _new_tool_call_id(tool)
        # Errored tool runs sometimes arrive on this same channel — discriminate via ``error``
        # key so the wire stays semantically clean (success vs failure events are distinct).
        err = _str(data.get("error"))
        if err:
            emitter.emit_tool_call_error(
                tool=tool,
                tool_call_id=tcid,
                error=err,
                error_class=_str(data.get("error_class")),
                duration_ms=_int(data.get("duration_ms")),
            )
            emitter.emit_message_tool(tool_name=tool, phase="end", detail="error", call_id=tcid)
            return
        raw_out = data.get("output")
        diff_payload: dict[str, str] | None = None
        out = ""
        if isinstance(raw_out, dict) and isinstance(raw_out.get("summary"), str):
            out = raw_out["summary"]
            b, a = raw_out.get("before"), raw_out.get("after")
            if isinstance(b, str) and isinstance(a, str):
                lang = raw_out.get("language")
                diff_payload = {
                    "before": b,
                    "after": a,
                    "language": _str(lang) or "",
                }
        else:
            out = _str(raw_out) or _str(data.get("content")) or ""
        ex = data.get("diff")
        if isinstance(ex, dict) and isinstance(ex.get("before"), str) and isinstance(ex.get("after"), str):
            diff_payload = {
                "before": ex["before"],
                "after": ex["after"],
                "language": _str(ex.get("language")) or "",
            }
        emitter.emit_tool_call_result(
            tool=tool,
            tool_call_id=tcid,
            output_preview=out or "",
            output_bytes=len(out) if out else 0,
            duration_ms=_int(data.get("duration_ms")),
            truncated=False,
            diff=diff_payload,
        )
        skill_name = _str(data.get("skill_name"))
        if not skill_name:
            args_obj = data.get("args")
            if isinstance(args_obj, dict):
                skill_name = _str(args_obj.get("name"))
        if tool == "load_skill" and skill_name:
            emitter.emit_skill_loaded(skill_name=skill_name, source="tool", body_chars=len(out) if out else 0)
        emitter.emit_message_tool(tool_name=tool, phase="end", detail="completed", call_id=tcid)
        return

    if et == "graph_node_enter":
        emitter.emit_graph_node_enter(
            node=_str(data.get("node")) or et,
            pattern=_str(data.get("pattern")),
            input_preview=_str(data.get("input_preview")) or _str(data.get("input")),
        )
        return

    if et == "graph_node_exit":
        emitter.emit_graph_node_exit(
            node=_str(data.get("node")) or et,
            pattern=_str(data.get("pattern")),
            duration_ms=_int(data.get("duration_ms")),
            output_preview=_str(data.get("output_preview")) or _str(data.get("output")),
            error=_str(data.get("error")),
        )
        return

    if et == "progress":
        emitter.emit_progress_step(
            phase=_str(data.get("phase")) or "setup",
            label=_str(data.get("name")),
            detail=_str(data.get("output")),
            elapsed_ms=_int(data.get("duration_ms")),
        )
        return

    if et == "skill_context":
        raw = data.get("skills") or data.get("skill_names")
        skills = [str(n) for n in raw if n is not None] if isinstance(raw, list) else []
        emitter.emit_skill_applied(
            phase=_str(data.get("phase")) or "classifier",
            injected_chars=_int(data.get("injected_chars")) or 0,
            skills=skills,
            context_preview=_str(data.get("context_preview")) or "",
            truncated=bool(data.get("truncated")),
        )
        return

    if et == "skill_learned":
        emitter.emit_skill_learned(
            skill_name=_str(data.get("skill_name")) or "unknown",
            pattern=_str(data.get("pattern")) or None,
            scope=_str(data.get("scope")) or None,
            source=_str(data.get("source")) or None,
        )
        return

    if et == "memory_lt_recall":
        emitter.emit_memory_lt_recall(
            namespace=_str(data.get("namespace")),
            query_preview=_str(data.get("query_preview")),
            hits=_int(data.get("hits")) or 0,
            injected_chars=_int(data.get("injected_chars")) or 0,
        )
        return

    if et == "memory_session_write":
        emitter.emit_memory_session_write(
            thread=_str(data.get("thread")) or emitter._thread,
            run_id=_str(data.get("run_id")),
            query_preview=_str(data.get("query_preview")),
            output_preview=_str(data.get("output_preview")),
            turn_count=_int(data.get("turn_count")),
        )
        return

    if et == "memory_lt_store":
        emitter.emit_memory_lt_store(
            namespace=_str(data.get("namespace")),
            key=_str(data.get("key")),
            content_preview=_str(data.get("content_preview")),
        )
        return

    if et == "checkpoint_saved":
        thread = _str(data.get("thread")) or emitter._thread
        emitter.emit_checkpoint_saved(
            thread=thread,
            run_id=_str(data.get("run_id")),
            label=_str(data.get("label")),
        )
        return

    if et == "checkpoint_restored":
        thread = _str(data.get("thread")) or emitter._thread
        emitter.emit_checkpoint_restored(
            thread=thread,
            resumed_from_run_id=_str(data.get("resumed_from_run_id")),
        )
        return

    if et == "feedback_scored":
        run_id = _str(data.get("run_id")) or ""
        emitter.emit_feedback_scored(
            run_id=run_id,
            rating=_str(data.get("rating")) or "neutral",
            comment=_str(data.get("comment")) or "",
            correct=_str(data.get("correct")) or "",
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
        )
        return

    if et == "worker_start":
        worker_id = _str(data.get("worker_id")) or _str(data.get("name")) or _str(data.get("id")) or "worker"
        emitter.emit_worker_spawned(
            worker_id=worker_id,
            name=_str(data.get("name")),
            pattern=_str(data.get("pattern")),
            task=_str(data.get("task")) or _str(data.get("output")),
            parent_worker_id=_str(data.get("parent_worker_id")) or _str(data.get("parent")),
        )
        return

    if et == "worker_end":
        worker_id = _str(data.get("worker_id")) or _str(data.get("name")) or _str(data.get("id")) or "worker"
        signal = _str(data.get("signal"))
        # Errored workers ride the same channel — discriminate via ``error`` / ``signal``, mirroring
        # the ``tool_result`` → ``tool.call.error`` pattern so the wire stays semantically clean.
        err = _str(data.get("error"))
        if signal == "HALTED":
            out = _str(data.get("output")) or _str(data.get("content")) or ""
            emitter.emit_worker_halted(
                worker_id=worker_id,
                reason=err or "HALT_ALL",
                output_preview=out or "",
                duration_ms=_int(data.get("duration_ms")),
            )
            return
        if err:
            emitter.emit_worker_failed(
                worker_id=worker_id,
                error=err,
                error_class=_str(data.get("error_class")),
                duration_ms=_int(data.get("duration_ms")),
            )
            return
        out = _str(data.get("output")) or _str(data.get("content")) or ""
        emitter.emit_worker_completed(
            worker_id=worker_id,
            output_preview=out or "",
            output_bytes=len(out) if out else 0,
            duration_ms=_int(data.get("duration_ms")),
            truncated=False,
        )
        return

    if et == "llm_call":
        # ``llm_call`` carries both reasoning-trace info AND token usage. Emit both: a
        # ``thinking.step`` for the trace pane and (when usage is present) ``metric.tokens``
        # for the sidebar rollup.
        emitter.emit_thinking_step(
            step="llm_call",
            label=_str(data.get("name")) or "llm",
            detail=_str(data.get("output")),
            elapsed_ms=_int(data.get("duration_ms")),
        )
        input_t = 0
        output_t = 0
        total_t: int | None = None
        usage = data.get("usage")
        if isinstance(usage, dict):
            input_t = _int(usage.get("input_tokens")) or _int(usage.get("prompt_tokens")) or 0
            output_t = _int(usage.get("output_tokens")) or _int(usage.get("completion_tokens")) or 0
            total_t = _int(usage.get("total_tokens"))
            if input_t or output_t or total_t:
                emitter.emit_metric_tokens(
                    input_tokens=input_t,
                    output_tokens=output_t,
                    total_tokens=total_t,
                    model=_str(data.get("model")) or _str(usage.get("model")),
                    phase=_str(data.get("phase")) or _str(data.get("name")),
                )
        if total_t is not None and not input_t and not output_t:
            tt = total_t
            input_t = tt // 2
            output_t = tt - input_t
        raw_cost = data.get("cost")
        cost = _float(raw_cost) if raw_cost is not None else None
        cost_estimated = False
        if cost is None or cost <= 0.0:
            if input_t or output_t:
                from agloom.llm.rough_cost import estimate_llm_cost_usd

                est = estimate_llm_cost_usd(
                    model=_str(data.get("model")),
                    input_tokens=input_t,
                    output_tokens=output_t,
                )
                if est > 0.0:
                    cost = est
                    cost_estimated = True
        if cost is not None and cost > 0.0:
            emitter.emit_metric_cost(
                cost=cost,
                currency=_str(data.get("currency")) or "USD",
                model=_str(data.get("model")),
                phase=_str(data.get("phase")) or _str(data.get("name")),
                estimated=cost_estimated,
            )
        budget = getattr(emitter, "budget_tracker", None)
        if budget is not None:
            if input_t or output_t:
                budget.record_tokens_delta(emitter, input_tokens=input_t, output_tokens=output_t)
            if cost is not None and cost > 0.0:
                budget.record_cost_delta(emitter, cost=cost)
        return

    if et in _AGENT_EVENT_THINKING_TYPES:
        emitter.emit_thinking_step(
            step=et,
            label=_str(data.get("name")) or et,
            detail=_str(data.get("output")),
            elapsed_ms=_int(data.get("duration_ms")),
        )
        return

    if et == "orchestration":
        emitter.emit_orchestration_step(
            depth=_int(data.get("depth")) or 0,
            pattern=_str(data.get("pattern")) or "UNKNOWN",
            action=_str(data.get("action")) or "step",
            worker_id=_str(data.get("worker_id")),
            reason=_str(data.get("reason")),
            input_preview=_str(data.get("input_preview")),
            output_preview=_str(data.get("output_preview")),
            duration_ms=_int(data.get("duration_ms")),
            error=_str(data.get("error")),
            confidence=_float(data.get("confidence")),
            quality_score=_float(data.get("quality_score")),
        )
        return

    if et == "runtime.mcp.servers":
        names = data.get("server_names", [])
        srv = data.get("servers")
        if not isinstance(names, list):
            names = []
        if not isinstance(srv, list):
            srv = []
        emitter.emit_runtime_mcp_servers(
            server_names=[str(n) for n in names],
            servers=[dict(r) for r in srv if isinstance(r, dict)],
        )
        return

    if et == "error":
        msg = _str(data.get("error")) or _str(data.get("message")) or "unknown error"
        emitter.emit_error(
            severity=_str(data.get("severity")) or "fatal",
            message=msg,
            error_class=_str(data.get("error_class")),
            stage=_str(data.get("stage")) or "invocation",
        )
        return msg

    # Forward-compat: unknown types — emit full output as ``thinking.step`` when present.
    if et not in _TRANSLATED_AGENT_EVENT_TYPES:
        msg = f"translate: unmapped AgentEvent type {et!r}"
        if _TRANSLATOR_VERBOSE_THINKING:
            logger.warning(msg)
        else:
            logger.debug(msg)
    detail = _str(data.get("output"))
    if not detail:
        return
    emitter.emit_thinking_step(
        step=et,
        label=_str(data.get("name")) or et,
        detail=detail,
        elapsed_ms=_int(data.get("duration_ms")),
    )


def _str(v: Any) -> str | None:
    """Best-effort string coercion that returns ``None`` for empty / missing values."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


__all__ = ["translate"]
