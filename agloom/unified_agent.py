"""Agent runtime: pattern routing, turn execution, and ``UnifiedAgent`` facade.

``create_agent`` / ``create_agent_sync`` validate configuration and return ``UnifiedAgent``.
The default path is ``ainvoke`` / ``astream`` / ``astream_events``; a compiled LangGraph is
materialized when needed for ``get_state``, ``get_history``, and ``resume``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import inspect
import sys
import threading
import time
import uuid
import weakref
from collections import OrderedDict
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool

from .classifier import analyze_query
from .compat import ensure_langchain_pending_deprecation_suppressed
from .delegation import (
    BackgroundDelegationManager,
    HandoffTarget,
    _build_delegation_context,
    make_agent_tool,
    resolve_handoff,
    run_delegate,
)
from .hitl_contract import HITLEvent, call_user_callback
from .logging_utils import configure_package_logging, get_logger
from .mcp_support import MCPConnectionError, MCPServerConfig, aclose_mcp_client
from .memory import (
    LongTermStore,
    SessionMemory,
    build_memory_context,
    create_memory_tools,
)
from .multimodal import content_blocks_to_text
from .models import (
    DEFAULT_SYSTEM_PROMPT,
    AgentConfig,
    AgentEvent,
    AgentStep,
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    StepType,
    _extract_token_usage,
    _make_step,
    _merge_token_usage,
)
from .multimodal import merge_context_into_user_turn, text_from_user_turn
from .patterns.blackboard import handle_blackboard
from .patterns.hybrid_dag import handle_hybrid_dag
from .patterns.pipeline import handle_pipeline
from .patterns.planner_executor import handle_planner_executor
from .patterns.react import handle_react
from .patterns.reflection import handle_reflection
from .patterns.supervisor import handle_supervisor
from .patterns.swarm import handle_swarm
from .wire_execution_result import execution_result_wire_dict
from .wire_tokens import record_emitted_usage

try:
    from .feedback.wireup import (
        apply_user_feedback,
        build_feedback_system,
        run_fresh_feedback_hooks,
    )

    _FEEDBACK_AVAILABLE = True
except ImportError:
    _FEEDBACK_AVAILABLE = False

    def build_feedback_system(*_, **__) -> dict:
        return {}

    def run_fresh_feedback_hooks(*_, **__) -> None:
        pass

    async def apply_user_feedback(*_, **__) -> None:
        pass


try:
    from .harness.git import (
        GitSession,
        git_checkpoint_tool,
        git_commit_tool,
        git_diff_tool,
        git_log_tool,
        git_revert_hint_tool,
        git_status_tool,
    )
    from .harness.initializer import create_initializer_tool
    from .harness.progress import (
        ProgressTracker,
        add_task_tool,
        bootstrap_progress_tool,
        get_next_task_tool,
        get_progress_tracker,
        save_progress_tool,
        update_task_tool,
    )

    _HARNESS_AVAILABLE = True
except ImportError:
    _HARNESS_AVAILABLE = False

    ProgressTracker = None
    GitSession = None
    create_initializer_tool = None

    def _no_harness(*_, **__):
        return lambda: None

    get_progress_tracker = _no_harness
    bootstrap_progress_tool = _no_harness
    save_progress_tool = _no_harness
    update_task_tool = _no_harness
    get_next_task_tool = _no_harness
    add_task_tool = _no_harness
    git_status_tool = _no_harness
    git_log_tool = _no_harness
    git_commit_tool = _no_harness
    git_checkpoint_tool = _no_harness
    git_revert_hint_tool = _no_harness
    git_diff_tool = _no_harness


logger = get_logger(__name__)


def _wire_query_snapshot(query: Any) -> str:
    if isinstance(query, str):
        return query
    if isinstance(query, list):
        return text_from_user_turn(query)
    return str(query)


async def _handle_direct(
    agent: dict,
    query: str | list,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """DIRECT handler: use classifier text or a single LLM call; stream if ``_event_queue`` is set."""
    steps: list[AgentStep] = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    output = (analysis.direct_response or "").strip()
    event_queue = agent.get("_event_queue")
    ml = agent.get("max_step_output_length", 0)
    raw_messages: list = []

    if not output:
        _timeout = agent.get("llm_timeout", 120.0)
        _raw_sp = agent.get("system_prompt")
        _sys_body = _raw_sp.strip() if isinstance(_raw_sp, str) and _raw_sp.strip() else DEFAULT_SYSTEM_PROMPT
        messages = [
            SystemMessage(content=_sys_body),
            HumanMessage(content=query),
        ]
        t0 = time.perf_counter()

        if event_queue is not None:
            chunks: list[str] = []
            last_chunk = None

            async def _stream():
                nonlocal last_chunk
                async for chunk in agent["llm"].astream(messages):
                    last_chunk = chunk
                    content = getattr(chunk, "content", "")
                    if content:
                        content = content_blocks_to_text(content)
                        chunks.append(content)
                        await _emit_token_event(agent, content)

            await asyncio.wait_for(_stream(), timeout=_timeout)
            output = "".join(chunks)
            usage = _extract_token_usage(last_chunk) if last_chunk else {}
            raw_messages = messages + ([last_chunk] if last_chunk else [])
        else:
            response = await asyncio.wait_for(
                agent["llm"].ainvoke(messages),
                timeout=_timeout,
            )
            output = content_blocks_to_text(response.content)
            usage = _extract_token_usage(response)
            raw_messages = messages + [response]

        dur = round((time.perf_counter() - t0) * 1000, 1)
        step = _make_step(
            StepType.LLM_CALL,
            "direct_llm",
            input=text_from_user_turn(query) if isinstance(query, list) else query,
            output=output,
            duration_ms=dur,
            max_length=ml,
            usage=usage,
            model=_llm_label(agent["llm"]),
            phase="direct_llm",
        )
        steps.append(step)
        await _emit_step_event(agent, step)

    return ExecutionResult(
        pattern_used=PatternType.DIRECT,
        query=query,
        output=output,
        steps_taken=1,
        success=True,
        analysis=analysis,
        steps=steps,
        token_usage=usage,
        messages=raw_messages,
    )


_HANDLERS: dict[PatternType, Any] = {
    PatternType.DIRECT: _handle_direct,
    PatternType.REACT: handle_react,
    PatternType.SUPERVISOR: handle_supervisor,
    PatternType.PIPELINE: handle_pipeline,
    PatternType.PLANNER_EXECUTOR: handle_planner_executor,
    PatternType.REFLECTION: handle_reflection,
    PatternType.SWARM: handle_swarm,
    PatternType.HYBRID_DAG: handle_hybrid_dag,
    PatternType.BLACKBOARD: handle_blackboard,
}


def resolve_model(model: Any) -> BaseChatModel:
    """Accept a ``BaseChatModel`` instance or a model-id string.

    Strings use :func:`agloom.llm.model_resolver.get_model` (provider routing and env keys).
    Pass a preconfigured ``BaseChatModel`` instance to set temperature and other kwargs.
    """
    if isinstance(model, str):
        from agloom.llm.model_resolver import get_model

        return get_model(model)
    return model


_STEP_TO_EVENT: dict[StepType, str] = {
    StepType.CLASSIFY: "thinking",
    StepType.LLM_CALL: "llm_call",
    StepType.TOOL_CALL: "tool_call",
    StepType.TOOL_RESULT: "tool_result",
    StepType.WORKER_START: "worker_start",
    StepType.WORKER_END: "worker_end",
    StepType.CACHE_HIT: "cache_hit",
    StepType.REFLECTION: "reflection",
    StepType.FALLBACK: "fallback",
    StepType.INTERRUPT: "interrupt",
    StepType.TOKEN: "token",
}


def _step_type_to_event_type(st: StepType) -> str:
    return _STEP_TO_EVENT.get(st, st.value)


async def _emit_graph_node_event(config: dict, event_type: str, *, node: str, pattern: str | None = None, **kwargs: object) -> None:
    """Emit a graph node enter/exit event to ``_event_queue`` when present."""
    queue = config.get("_event_queue")
    if queue is None:
        return
    await queue.put(
        AgentEvent(
            type=event_type,
            data={"node": node, "pattern": pattern, **{k: v for k, v in kwargs.items() if v is not None}},
        )
    )


async def _emit_step_event(config: dict, step: AgentStep) -> None:
    """Emit a step to ``_event_queue`` when present."""
    queue = config.get("_event_queue")
    if queue is None:
        return
    event_type = _step_type_to_event_type(step.type)
    data = {
        "name": step.name,
        "input": step.input,
        "output": step.output,
        "duration_ms": step.duration_ms,
        **step.metadata,
    }
    await queue.put(AgentEvent(type=event_type, data=data))
    if event_type == "llm_call":
        usage_raw = data.get("usage")
        if isinstance(usage_raw, dict):
            record_emitted_usage(config, usage_raw)
            step.metadata["_wire_emitted"] = True


def _surrogate_safe_text(text: str) -> str:
    """Strip lone surrogates so JSON/wire consumers never see invalid UTF-16."""
    if not text:
        return text
    return text.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


async def _emit_token_event(config: dict, content: str) -> None:
    """Emit one token chunk to ``_event_queue``."""
    queue = config.get("_event_queue")
    if queue is None:
        return
    await queue.put(AgentEvent(type="token", data={"content": _surrogate_safe_text(content)}))


def _approx_char_tokens(text: str, *, cap_chars: int = 48_000) -> int:
    """Rough token estimate when provider usage metadata is absent (~4 chars per token)."""
    if not text:
        return 0
    if len(text) > cap_chars:
        text = text[:cap_chars]
    return max(1, len(text) // 4)


def _build_classifier_augmented_query(
    memory_ctx: str, harness_ctx: str, processed_query: str
) -> str:
    """Merge memory / harness snippets ahead of the user query for ``analyze_query``."""
    mem = memory_ctx.strip()
    har = harness_ctx.strip()
    harness_block = f"\n\n=== CROSS-SESSION PROGRESS ===\n{har}\n" if har else ""
    if mem:
        return f"{mem}{harness_block}\n{processed_query}"
    if harness_block:
        return f"{harness_block}\n{processed_query}"
    return processed_query


async def _resolve_system_prompt_for_turn(
    config: dict[str, Any],
    *,
    raw_query_str: str,
    context: dict,
    thread_id: str,
    user_id: str | None,
) -> dict[str, Any]:
    """Resolve callable ``system_prompt`` and return an updated agent config dict."""
    sp = config["system_prompt"]
    if callable(sp) and not isinstance(sp, str):
        _sp_state = {
            "messages": [],
            "query": raw_query_str,
            "context": context,
            "thread_id": thread_id,
            "user_id": user_id,
        }
        resolved_sp = await _maybe_await(sp(_sp_state))
        if isinstance(resolved_sp, SystemMessage):
            resolved_sp = (
                resolved_sp.content if isinstance(resolved_sp.content, str) else str(resolved_sp.content)
            )
        return {**config, "system_prompt": resolved_sp or DEFAULT_SYSTEM_PROMPT}
    return config


async def _build_harness_context_for_classify(config: dict[str, Any], *, is_frozen: bool) -> str:
    """Cross-session progress snippet for the classifier (skipped when frozen or harness off)."""
    if is_frozen or not config.get("_harness_enabled"):
        return ""
    progress_tracker: ProgressTracker | None = config.get("_progress_tracker")
    if progress_tracker is None:
        return ""
    try:
        return progress_tracker.get_classifier_context()
    except Exception as exc:
        name = config.get("name", "Agent")
        logger.warning(f"[{name}] harness bootstrap failed ({exc!r}) — proceeding")
        return ""


async def _build_skill_context_for_classify(config: dict[str, Any], *, processed_query: str) -> str:
    """Skill injector + delegation targets merged for the classifier."""
    skill_ctx = ""
    skill_injector = config.get("skill_injector")
    if skill_injector:
        try:
            skill_ctx = await skill_injector.get_context(processed_query)
        except Exception as exc:
            name = config.get("name", "Agent")
            logger.warning(f"[{name}] skill_injector failed ({exc!r}) — proceeding without.")

    handoff_targets = config.get("_handoff_targets") or []
    delegate_targets = config.get("_delegate_targets") or []
    delegation_ctx = _build_delegation_context(handoff_targets + delegate_targets)
    if delegation_ctx and skill_ctx:
        return f"{skill_ctx}\n\n{delegation_ctx}"
    if delegation_ctx:
        return delegation_ctx
    return skill_ctx


def _coerce_unknown_pattern_handler(
    config: dict[str, Any],
    analysis: QueryAnalysis,
    *,
    registry: dict[PatternType, Any],
) -> QueryAnalysis:
    """If the classifier picked a pattern with no handler, coerce to REACT."""
    if registry.get(analysis.pattern) is not None:
        return analysis
    name = config.get("name", "Agent")
    unknown_pattern = analysis.pattern.value
    logger.warning(
        f"[{name}] Classifier returned pattern {unknown_pattern!r} "
        "with no registered handler — coercing to REACT."
    )
    return analysis.model_copy(
        update={
            "pattern": PatternType.REACT,
            "reasoning": (
                f"{analysis.reasoning or ''} [pattern {unknown_pattern} has no handler; using REACT]"
            ).strip(),
        }
    )


async def _execute_analyze_query(
    cfg: dict[str, Any],
    *,
    augmented_query: str,
    skill_context: str,
) -> QueryAnalysis:
    """Invoke :func:`~agloom.classifier.analyze_query` using classifier fields from *cfg*."""
    fp = cfg.get("fallback_pattern")
    fallback = fp if isinstance(fp, PatternType) else None
    return await analyze_query(
        llm=cfg["llm"],
        query=augmented_query,
        tools=list(cfg.get("tools") or []),
        skill_context=skill_context,
        classifier_timeout=float(cfg.get("classifier_timeout", 60.0)),
        structured_max_retries=int(cfg.get("structured_max_retries", 2)),
        fallback_pattern=fallback,
    )


def _llm_label(llm: Any) -> str | None:
    for attr in ("model_name", "model", "model_id"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    cls = getattr(llm, "__class__", None)
    return cls.__name__ if cls is not None else None


RESERVED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "save_memory",
        "recall_memory",
        "load_skill",
    }
)

_active_agent_names_by_store: weakref.WeakKeyDictionary[Any, dict[str, int]] = weakref.WeakKeyDictionary()
_active_agent_names_no_store: dict[str, int] = {}
_agent_names_lock = threading.Lock()

_SYNC_BRIDGE_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None
_SYNC_BRIDGE_EXECUTOR_LOCK = threading.Lock()


def _sync_bridge_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Shared pool for ``invoke`` / ``create_agent_sync`` when an event loop is already running."""
    global _SYNC_BRIDGE_EXECUTOR
    with _SYNC_BRIDGE_EXECUTOR_LOCK:
        if _SYNC_BRIDGE_EXECUTOR is None:
            _SYNC_BRIDGE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
                max_workers=4,
                thread_name_prefix="agloom-sync",
            )
        return _SYNC_BRIDGE_EXECUTOR


def _run_coroutine_in_new_loop(coro: Awaitable[Any]) -> Any:
    if asyncio.iscoroutine(coro):
        return asyncio.run(coro)

    async def _wrap() -> Any:
        return await coro

    return asyncio.run(_wrap())


def _check_reserved_tool_names(tools: list[BaseTool]) -> None:
    """Raise ValueError if any user tool collides with agloom's internal tool names."""
    collisions = {t.name for t in tools} & RESERVED_TOOL_NAMES
    if collisions:
        names = ", ".join(sorted(collisions))
        raise ValueError(
            f"Tool name(s) {names} are reserved by agloom for internal use. "
            f"Please rename your tool(s) to avoid conflicts. "
            f"Reserved names: {sorted(RESERVED_TOOL_NAMES)}"
        )


def _register_agent_name(agent_name: str, store: Any) -> None:
    """Track agent name and warn if a duplicate shares the same LongTermStore.

    Keys on the store **object** (``WeakKeyDictionary``), not ``id(store)``, so a
    recycled object id after GC does not look like a duplicate registration.
    """
    with _agent_names_lock:
        if store is None:
            _active_agent_names_no_store[agent_name] = _active_agent_names_no_store.get(agent_name, 0) + 1
            count = _active_agent_names_no_store[agent_name]
        else:
            per = _active_agent_names_by_store.get(store)
            if per is None:
                per = {}
                _active_agent_names_by_store[store] = per
            per[agent_name] = per.get(agent_name, 0) + 1
            count = per[agent_name]
    if count > 1 and store is not None:
        logger.warning(
            f"[agloom] Multiple agents named '{agent_name}' share the same "
            f"LongTermStore instance. They will share feedback records, "
            f"correction memory, learned skills, and LT memory namespaces. "
            f"If this is unintentional, use distinct names or separate stores."
        )


def _unregister_agent_name(agent_name: str, store: Any) -> None:
    """Remove an agent from the active name tracker (called on aclose)."""
    with _agent_names_lock:
        if store is None:
            c = _active_agent_names_no_store.get(agent_name, 0)
            if c <= 1:
                _active_agent_names_no_store.pop(agent_name, None)
            else:
                _active_agent_names_no_store[agent_name] = c - 1
            return
        per = _active_agent_names_by_store.get(store)
        if not per:
            return
        count = per.get(agent_name, 0)
        if count <= 1:
            per.pop(agent_name, None)
            if not per:
                try:
                    del _active_agent_names_by_store[store]
                except KeyError:
                    pass
        else:
            per[agent_name] = count - 1


def _structured_tool_from_callable(
    fn: Callable[..., Any],
    *,
    name: str | None = None,
    description: str = "",
) -> StructuredTool:
    """Wrap a sync or async callable so LangChain awaits coroutine tools correctly."""
    nm = name or getattr(fn, "__name__", "tool")
    if nm == "<lambda>":
        nm = f"callable_tool_{abs(id(fn)):x}"
    desc = (description or "").strip() or (getattr(fn, "__doc__", None) or "").strip() or f"Tool: {nm}"
    if inspect.iscoroutinefunction(fn):
        return StructuredTool.from_function(coroutine=fn, name=nm, description=desc)
    return StructuredTool.from_function(func=fn, name=nm, description=desc)


def normalize_tools(tools: Sequence[Any]) -> list[BaseTool]:
    """Normalise a mixed list (BaseTool, callable, dict) to BaseTool instances."""
    normalised: list[BaseTool] = []
    for t in tools:
        if isinstance(t, BaseTool):
            normalised.append(t)
        elif callable(t):
            normalised.append(_structured_tool_from_callable(t))
        elif isinstance(t, dict):
            fn = t.get("function") or t.get("func")
            if fn:
                normalised.append(
                    _structured_tool_from_callable(
                        fn,
                        name=t.get("name", getattr(fn, "__name__", "tool")),
                        description=str(t.get("description", "")),
                    )
                )
            else:
                logger.warning("normalize_tools: dict tool has no callable — skipped.")
        else:
            logger.warning(f"normalize_tools: unknown type {type(t)} — skipped.")
    return normalised


def resolve_system_prompt(system_prompt: Any) -> str | Callable:
    """Accept str, SystemMessage, Callable, or None. Callables are deferred to per-run resolution."""
    if callable(system_prompt) and not isinstance(system_prompt, str):
        return system_prompt
    if isinstance(system_prompt, SystemMessage):
        content = system_prompt.content
        return content if isinstance(content, str) else str(content)
    return system_prompt or DEFAULT_SYSTEM_PROMPT


async def _maybe_await(value: Any) -> Any:
    """Transparently await coroutines; return sync values as-is."""
    if inspect.isawaitable(value):
        return await value
    return value


async def _run_before_agent(
    middleware: list,
    query: str,
    context: dict,
) -> str:
    """Run all before_agent middleware in order. Each may transform the query."""
    for mw in middleware:
        if hasattr(mw, "before_agent"):
            result = await _maybe_await(mw.before_agent(query, context))
            if result is not None:
                query = result
    return query


async def _run_after_agent(
    middleware: list,
    result: ExecutionResult,
    context: dict,
) -> ExecutionResult:
    """Run all after_agent middleware in reverse order."""
    for mw in reversed(middleware):
        if hasattr(mw, "after_agent"):
            updated = await _maybe_await(mw.after_agent(result, context))
            if updated is not None:
                result = updated
    return result


async def _check_pattern_interrupt(
    config: dict,
    phase: str,  # "before" | "after"
    pattern: str,
    query: str,
    result: ExecutionResult | None = None,
) -> bool:
    """L1 interrupt via user_callback. Returns True=continue, False=abort. Fail-open on errors."""
    callback = config.get("user_callback")
    if not callback:
        return True

    preview = f"\nOutput: {result.output}" if result else ""
    message = f"{config['name']} INTERRUPT-{phase.upper()} [{pattern}]\nQuery: {query}{preview}"
    logger.event(f"[HITL-L1] {message}")
    try:
        decision = await call_user_callback(callback, HITLEvent.PATTERN_INTERRUPT, message)
        return str(decision).strip().lower() not in ("no", "abort", "stop", "cancel")
    except Exception as exc:
        logger.error(f"[HITL-L1] user_callback raised {exc!r} — continuing (fail-open).")
        return True


async def _apply_response_format(
    llm: Any,
    result: ExecutionResult,
    response_format: Any,
    llm_timeout: float = 120.0,
    structured_max_retries: int = 2,
) -> ExecutionResult:
    """Optionally reshape output into a structured format via with_structured_output."""
    if response_format is None:
        return result
    try:
        from .llm_utils import robust_structured_call

        formatted = await robust_structured_call(
            llm,
            response_format,
            [HumanMessage(content=f"Reformat into required structure:\n{result.output}")],
            max_retries=structured_max_retries,
            timeout=llm_timeout,
            caller="response_format",
        )
        if formatted is None:
            logger.warning("response_format: structured call returned None — using raw output.")
            return result
        return result.model_copy(update={"output": formatted if isinstance(formatted, str) else str(formatted)})
    except Exception as exc:
        logger.warning(f"response_format failed ({exc!r}) — using raw output.")
        return result


def _memory_injection_last_n(config: dict) -> int:
    """How many recent turns to inject into prompts (bounded for safety; honors ``session_max_turns``)."""
    try:
        n = int(config.get("session_max_turns", 50))
    except (TypeError, ValueError):
        n = 50
    # Avoid pathological context sizes; rolling SessionMemory may still store more per YAML.
    return max(1, min(n, 500))


def _max_tokens_budget_from_chat_model(llm: Any) -> int | None:
    """Best-effort read of ``max_tokens`` from a chat model for session-memory summarize budget."""
    if llm is None:
        return None
    v = getattr(llm, "max_tokens", None)
    if isinstance(v, int) and v > 0:
        return v
    mk = getattr(llm, "model_kwargs", None)
    if isinstance(mk, dict):
        raw = mk.get("max_tokens")
        if isinstance(raw, int) and raw > 0:
            return raw
    return None


async def _record_turn(
    memory: SessionMemory | None,
    thread_id: str,
    query: str,
    result: ExecutionResult,
    user_id: str | None,
    effective_ltns: tuple,
) -> None:
    """Record completed turn in session memory. Swallows errors to never crash the run."""
    if not memory:
        return
    try:
        query_str = query if isinstance(query, str) else str(query)
        await memory.aadd_turn(
            thread_id=thread_id,
            query=query_str,
            output=result.output,
            pattern=result.pattern_used.value,
            metadata={
                "user_id": user_id,
                "lt_namespace": list(effective_ltns),
                "run_id": result.run_id,
            },
        )
    except Exception as exc:
        logger.warning(f"_record_turn failed (non-fatal): {exc!r}")


async def _resolve_new_channel_versions(
    checkpointer: Any,
    config: dict,
    channel_keys: list[str],
) -> dict[str, Any]:
    """Build monotonic ``channel_versions`` for :meth:`BaseCheckpointSaver.aput`.

    Re-using version ``1`` for every channel on every save makes LangGraph stores point
    multiple checkpoints at the same blob keys, so history loads the **latest** values
    for every past checkpoint. We bump per channel using the checkpointer's own
    :meth:`get_next_version` when available.
    """
    prev_versions: dict[str, Any] = {}
    try:
        if hasattr(checkpointer, "aget_tuple"):
            tup = await checkpointer.aget_tuple(config)
        elif hasattr(checkpointer, "get_tuple"):
            tup = await asyncio.to_thread(checkpointer.get_tuple, config)
        else:
            tup = None
        if tup is not None:
            ch = tup.checkpoint if hasattr(tup, "checkpoint") else None
            if isinstance(ch, dict):
                cv = ch.get("channel_versions")
                if isinstance(cv, dict):
                    prev_versions = dict(cv)
            elif ch is not None:
                cv = getattr(ch, "channel_versions", None)
                if isinstance(cv, dict):
                    prev_versions = dict(cv)
                else:
                    logger.warning(
                        "resolve_new_channel_versions_no_dict",
                        checkpoint_type=type(ch).__name__,
                    )
    except Exception as exc:
        logger.debug(f"_resolve_new_channel_versions: could not read prior tuple ({exc!r})")

    get_next = getattr(checkpointer, "get_next_version", None)
    out: dict[str, Any] = {}
    for k in channel_keys:
        if callable(get_next):
            out[k] = get_next(prev_versions.get(k), None)
            continue
        cur = prev_versions.get(k)
        if cur is None:
            out[k] = 1
        elif isinstance(cur, int):
            out[k] = cur + 1
        elif isinstance(cur, str):
            try:
                out[k] = int(cur.split(".")[0]) + 1
            except ValueError:
                out[k] = 1
        else:
            try:
                out[k] = int(cur) + 1
            except (TypeError, ValueError):
                out[k] = 1
    return out


def _analysis_from_checkpoint_values(channel_values: dict[str, Any]) -> QueryAnalysis | None:
    """Restore ``QueryAnalysis`` saved by :func:`_save_checkpoint` (or graph state)."""
    raw = channel_values.get("analysis")
    if raw is None:
        return None
    if isinstance(raw, QueryAnalysis):
        return raw
    if isinstance(raw, dict):
        try:
            return QueryAnalysis.model_validate(raw)
        except Exception:
            return None
    return None


def _analysis_from_checkpointer_tuple(checkpoint_tuple: Any) -> QueryAnalysis | None:
    """Read ``analysis`` from a LangGraph ``CheckpointTuple`` or dict-shaped snapshot."""
    if checkpoint_tuple is None:
        return None
    try:
        ck = getattr(checkpoint_tuple, "checkpoint", None)
        if ck is None and isinstance(checkpoint_tuple, dict):
            ck = checkpoint_tuple.get("checkpoint")
        if not isinstance(ck, dict):
            return None
        cv = ck.get("channel_values")
        if isinstance(cv, dict):
            return _analysis_from_checkpoint_values(cv)
    except Exception:
        return None
    return None


async def _seed_graph_state_for_resume(
    compiled: Any,
    cfg: dict,
    *,
    analysis: QueryAnalysis | None,
    query: str | None,
) -> None:
    """Patch graph state via ``aupdate_state`` before ``Command(resume=…)``.

    When ``analysis`` is set, :func:`agloom.graph._make_classify_node` no-ops and routing
    reuses the pattern chosen before the interrupt.
    """
    if analysis is None and not query:
        return
    patch: dict[str, Any] = {}
    if analysis is not None:
        patch["analysis"] = analysis
    if query:
        patch["query"] = query
    if not patch:
        return
    if hasattr(compiled, "aupdate_state"):
        await compiled.aupdate_state(cfg, patch)
    elif hasattr(compiled, "update_state"):
        compiled.update_state(cfg, patch)


async def _save_checkpoint(
    checkpointer: Any,
    thread_id: str,
    result: ExecutionResult,
    query: str,
    *,
    event_queue: Any = None,
    label: str | None = None,
) -> None:
    """Best-effort checkpoint write for ``get_state`` / ``get_history`` / ``resume``.

    Persists query, output, steps, token usage, and ``result.analysis`` (when set) under
    ``channel_values`` so interrupted graph runs can skip re-classification.
    """
    if checkpointer is None:
        return
    try:
        from datetime import UTC, datetime

        checkpoint_id = result.run_id or str(uuid.uuid4())
        channel_values = {
            "query": query,
            "output": result.output,
            "pattern": result.pattern_used.value,
            "success": result.success,
            "run_id": result.run_id,
            "steps_taken": result.steps_taken,
            "steps": [s.model_dump() for s in result.steps],
            "token_usage": result.token_usage,
            "message_count": len(result.messages),
        }
        if result.analysis is not None:
            channel_values["analysis"] = result.analysis.model_dump()
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        channel_versions = await _resolve_new_channel_versions(
            checkpointer,
            config,
            list(channel_values.keys()),
        )
        checkpoint = {
            "v": 1,
            "id": checkpoint_id,
            "ts": datetime.now(UTC).isoformat(),
            "channel_values": channel_values,
            "channel_versions": channel_versions,
            "versions_seen": {},
        }
        metadata = {
            "source": "loop",
            "step": result.steps_taken,
            "parents": {},
            "run_id": result.run_id,
        }
        if hasattr(checkpointer, "aput"):
            await checkpointer.aput(config, checkpoint, metadata, channel_versions)
        elif hasattr(checkpointer, "put"):
            await asyncio.to_thread(checkpointer.put, config, checkpoint, metadata, channel_versions)
        logger.debug(f"Checkpoint saved: thread_id={thread_id} run_id={result.run_id}")
        # Emit AGP checkpoint.saved so frontends / EventStore consumers know the state is durable.
        if event_queue is not None:
            await event_queue.put(
                AgentEvent(
                    type="checkpoint_saved",
                    data={"thread": thread_id, "run_id": result.run_id, "label": label},
                )
            )
    except Exception as exc:
        logger.warning(f"_save_checkpoint failed ({exc!r}) — non-fatal.")


async def _ensure_mcp_connected(config: dict) -> None:
    """Connect to MCP servers once per agent lifecycle; emit diagnostics (AGP + logs).

    Raises :class:`~agloom.mcp_support.MCPConnectionError` if any configured server fails
    (caller should surface as fatal to the user).
    """
    if not config.get("_mcp_servers"):
        return
    if config.get("_mcp_session_attempted"):
        return
    async with config["_mcp_lock"]:
        if config.get("_mcp_session_attempted"):
            return
        from .mcp_support import connect_mcp_servers

        client, server_rows = await connect_mcp_servers(
            servers=config["_mcp_servers"],
            agent=config,
            agent_name=config.get("name", "Agent"),
        )
        config["_mcp_session_attempted"] = True
        config["_mcp_client"] = client
        config["_mcp_server_rows"] = list(server_rows)
        if client is not None:
            config["_mcp_connected"] = True

        names = [getattr(s, "name", str(s)) for s in config.get("_mcp_servers", [])]
        eq = config.get("_event_queue")
        if eq is not None:
            await eq.put(
                AgentEvent(
                    type="runtime.mcp.servers",
                    data={"server_names": names, "servers": server_rows},
                )
            )

        parts: list[str] = []
        total_tools = 0
        for row in server_rows:
            if not row.get("ok"):
                err = row.get("error") or "unknown error"
                raise MCPConnectionError(f"MCP server {row.get('name')!r} failed: {err}")
            sname = row.get("name") or "?"
            tcount = int(row.get("tool_count") or 0)
            total_tools += tcount
            parts.append(f"{sname}: {tcount} tool(s)")
        if parts:
            summary = ", ".join(parts)
            logger.event("mcp_connected", summary=summary, total_tools=total_tools)
            sys.stderr.write(f"[agloom-runtime] MCP connected — {summary} (total {total_tools})\n")
            sys.stderr.flush()


async def _ensure_skills_bootstrapped(
    config: dict,
    *,
    event_queue: asyncio.Queue | None = None,
) -> None:
    """Bootstrap skills on first call: load from disk, auto-seed if empty, run lifecycle hygiene."""
    if config.get("_skills_bootstrapped") or config.get("skill_registry") is None:
        return

    async with config["_skills_lock"]:
        if config.get("_skills_bootstrapped"):
            return

        registry = config["skill_registry"]
        lifecycle = config["skill_lifecycle"]
        generator = config.get("skill_generator")
        agent_name = config.get("name", "Agent")

        await registry.bootstrap()

        manifests = await registry.list_manifests()
        tools = [t for t in config.get("tools", []) if t.name != "load_skill"]
        if not manifests and tools and generator:
            try:
                seed_skills = await generator.generate_seed_skills(tools, agent_name)
                for s in seed_skills:
                    await registry.save_learned_skill(
                        name=s.name,
                        description=s.description,
                        body=s.body,
                        scope="global",
                        tags=["seed", "auto-generated"],
                    )
                    if event_queue is not None:
                        await event_queue.put(
                            AgentEvent(
                                type="skill_learned",
                                data={
                                    "skill_name": s.name,
                                    "pattern": None,
                                    "scope": "global",
                                    "source": "seed",
                                },
                            )
                        )
                if seed_skills:
                    logger.event(
                        f"[{agent_name}] auto-generated {len(seed_skills)} seed skill(s) "
                        f"from tool inventory: {[s.name for s in seed_skills]}"
                    )
            except Exception as exc:
                logger.warning(f"[{agent_name}] seed skill generation failed ({exc!r}) — non-fatal.")

        if lifecycle:
            tool_names = {t.name for t in config.get("tools", [])}
            await lifecycle.on_startup(tool_names)

        config["_skills_bootstrapped"] = True


async def _ensure_harness_bootstrapped(
    config: dict,
    effective_thread_id: str,
    effective_ltns: tuple,
    query: str,
) -> None:
    """Create ``ProgressTracker`` once and bootstrap artifact per ``thread_id``."""
    if not config.get("_harness_enabled"):
        return
    tracker: ProgressTracker | None = config.get("_progress_tracker")
    if tracker is None:
        factory: Callable | None = config.get("_progress_tracker_factory")
        if factory is None:
            return
        try:
            tracker = await factory()
            config["_progress_tracker"] = tracker
        except Exception as exc:
            logger.warning(f"[{config.get('name', 'Agent')}] ProgressTracker creation failed ({exc!r})")
            return

    if getattr(tracker, "_bootstrapped_for_thread", None) == effective_thread_id:
        return

    try:
        await tracker.bootstrap(
            session_id=effective_thread_id,
            goal=query if isinstance(query, str) else str(query),
        )
        tracker._bootstrapped_for_thread = effective_thread_id
        logger.event(
            f"[{config.get('name', 'Agent')}] harness bootstrapped: "
            f"{len(tracker.artifact.tasks)} tasks, "
            f"progress={tracker.artifact.completion_ratio:.0%}"
        )
    except Exception as exc:
        logger.warning(f"[{config.get('name', 'Agent')}] harness bootstrap failed ({exc!r}) — proceeding")


def _validate_frozen_params(
    frozen: bool,
    frozen_template: str | None,
    input_key: str | list[str],
) -> None:
    """Validate frozen-mode params at construction time; raises ValueError on invalid input."""
    if not frozen:
        return
    if not frozen_template or not frozen_template.strip():
        raise ValueError(
            "frozen=True requires frozen_template. "
            "Provide a template string with {placeholder} for each input_key.\n"
            "Example:\n"
            "  create_agent(\n"
            "    frozen=True,\n"
            "    frozen_template='Classify this email: {input}',\n"
            "  )"
        )
    keys: list = [input_key] if isinstance(input_key, str) else list(input_key)
    if not keys:
        raise ValueError("input_key must be a non-empty str or non-empty list[str].")
    for k in keys:
        if not isinstance(k, str) or not k.strip():
            raise ValueError(f"Every value in input_key must be a non-empty string. Got: {k!r}")


async def _ensure_frozen_analysis(config: dict) -> None:
    """Lazy classify for frozen agents with TTL-based invalidation. Double-check locking via asyncio.Lock."""
    import time as _time

    frozen_ttl = config.get("frozen_analysis_ttl", 0)
    existing = config.get("frozen_analysis")

    if existing is not None:
        if frozen_ttl <= 0:
            return
        elapsed = _time.monotonic() - config.get("_frozen_analysis_ts", 0)
        if elapsed < frozen_ttl:
            return
        logger.event(
            f"[{config.get('name', 'Agent')}] frozen analysis expired "
            f"({elapsed:.0f}s > TTL {frozen_ttl}s) — re-classifying"
        )

    async with config["_frozen_lock"]:
        existing = config.get("frozen_analysis")
        if existing is not None:
            if frozen_ttl <= 0:
                return
            elapsed = _time.monotonic() - config.get("_frozen_analysis_ts", 0)
            if elapsed < frozen_ttl:
                return

        name = config.get("name", "Agent")
        logger.event(f"[{name}] frozen agent — classifying template: {config['frozen_template']!r}")

        analysis = await _execute_analyze_query(
            config,
            augmented_query=config["frozen_template"],
            skill_context="",
        )

        registry = config.get("registry", _HANDLERS)
        handler = registry.get(analysis.pattern)
        if handler is None:
            logger.warning(
                f"[{name}] No handler for frozen pattern '{analysis.pattern.value}' — falling back to REACT."
            )
            handler = handle_react

        config["frozen_analysis"] = analysis
        config["_frozen_handler"] = handler
        config["_frozen_analysis_ts"] = _time.monotonic()

        logger.event(
            f"[{name}] frozen agent locked — "
            f"pattern={analysis.pattern.value} "
            f"handler={handler.__name__} "
            f"subtasks={len(analysis.subtasks)} "
            f"(this analysis is reused for ALL subsequent calls)"
        )


def _apply_frozen_substitution(
    query: str | dict,
    frozen_template: str,
    system_prompt: str,
    analysis: QueryAnalysis,
    input_key: str | list[str],
) -> tuple[str, str, QueryAnalysis]:
    """Replace {input_key} placeholders in query, system_prompt, and subtask texts via model_copy."""
    keys: list = [input_key] if isinstance(input_key, str) else list(input_key)
    subs: dict = {keys[0]: query} if isinstance(query, str) else {k: str(v) for k, v in query.items()}

    def _sub(template: str) -> str:
        result = template
        placeholders: dict[str, str] = {}
        for i, (k, v) in enumerate(subs.items()):
            token = f"__AGLOOM_SUB_{i}__"
            placeholders[token] = v
            result = result.replace(f"{{{k}}}", token)
        for token, v in placeholders.items():
            result = result.replace(token, v)
        return result

    sub_query = _sub(frozen_template)
    sub_system_prompt = _sub(system_prompt)
    sub_analysis = analysis.model_copy(
        update={"subtasks": [st.model_copy(update={"task": _sub(st.task)}) for st in analysis.subtasks]}
    )
    return sub_query, sub_system_prompt, sub_analysis


def _extract_delegate_from_analysis(
    analysis: QueryAnalysis,
    targets: list[HandoffTarget],
) -> str | None:
    """Return a delegate name if the classifier reasoning matches a registered target."""
    import re

    if not targets:
        return None
    reasoning = (analysis.reasoning or "").lower()
    matched = (getattr(analysis, "matched_skill", None) or "").lower()
    for t in targets:
        t_lower = t.name.lower()
        if not t_lower:
            continue
        pat = re.compile(rf"\b{re.escape(t_lower)}\b")
        if pat.search(reasoning) or pat.search(matched):
            return t.name
    return None


async def run_fresh(
    config: dict,
    query: str | dict | list,
    effective_thread_id: str,
    effective_ltns: tuple,
    invoke_config: dict,
    context: dict,
    user_id: str | None = None,
) -> ExecutionResult:
    """Execute one user turn: middleware, memory, classify (unless frozen), handlers, skills, feedback hooks.

    ``config`` is the agent dict (see ``create_agent``). ``invoke_config`` carries per-run
    ``configurable`` (thread id, memory namespace, signal and clarification queues).
    Pattern-level ``interrupt_before`` is evaluated before the DIRECT short-circuit so it
    cannot be bypassed by a cached direct response.
    """
    name = config["name"]
    memory = config.get("memory")
    store = config.get("store")
    cache = config.get("query_cache")
    registry = config.get("registry", _HANDLERS)
    ml = config.get("max_step_output_length", 0)

    run_id = str(uuid.uuid4())
    _steps: list[AgentStep] = []
    _total_usage: dict[str, int] = {}

    from .wire_tokens import emit_remaining_token_usage, reset_wire_emitted_usage

    reset_wire_emitted_usage(config)

    if isinstance(query, str):
        raw_query_str = query
    elif isinstance(query, list):
        raw_query_str = text_from_user_turn(query)
    else:
        raw_query_str = " ".join(str(v) for v in query.values())

    processed_query = await _run_before_agent(config.get("middleware", []), raw_query_str, context)

    config = await _resolve_system_prompt_for_turn(
        config,
        raw_query_str=raw_query_str,
        context=context,
        thread_id=effective_thread_id,
        user_id=user_id,
    )

    memory_ctx = await build_memory_context(
        session=memory,
        store=store,
        thread_id=effective_thread_id,
        namespace=effective_ltns,
        query=processed_query,
        last_n=_memory_injection_last_n(config),
    )
    # Emit memory.lt.recall when LT store was actually searched.
    if store is not None:
        injected = len(memory_ctx) if memory_ctx else 0
        await _emit_graph_node_event(
            config,
            "memory_lt_recall",
            node="memory.lt.recall",
            namespace=".".join(str(p) for p in effective_ltns) if effective_ltns else None,
            query_preview=processed_query,
            hits=1 if injected > 0 else 0,
            injected_chars=injected,
        )

    is_frozen = bool(config.get("frozen") and config.get("frozen_analysis") is not None)

    harness_ctx = await _build_harness_context_for_classify(config, is_frozen=is_frozen)
    if harness_ctx and not is_frozen:
        progress_tracker: ProgressTracker | None = config.get("_progress_tracker")
        if progress_tracker is not None:
            logger.event(
                f"[{name}] harness bootstrap: "
                f"{len(progress_tracker.artifact.tasks)} tasks, "
                f"progress={progress_tracker.artifact.completion_ratio:.0%}"
            )

    if is_frozen:
        sub_query, sub_system_prompt, analysis = _apply_frozen_substitution(
            query=text_from_user_turn(query) if isinstance(query, list) else query,
            frozen_template=config["frozen_template"],
            system_prompt=config["system_prompt"],
            analysis=config["frozen_analysis"],
            input_key=config.get("input_key", "input"),
        )
        config = {**config, "system_prompt": sub_system_prompt}
        augmented_query = (
            f"{memory_ctx}\n{harness_ctx}\n{sub_query}"
            if memory_ctx
            else (f"{harness_ctx}\n{sub_query}" if harness_ctx else sub_query)
        )
        handler = config["_frozen_handler"]
        pattern_val = analysis.pattern.value
        logger.event(
            f"[{name}] frozen path — pattern={pattern_val} (skipped skill injection, classify, handler lookup)"
        )
    else:
        handoff_targets = config.get("_handoff_targets") or []
        delegate_targets = config.get("_delegate_targets") or []
        all_delegation_targets = handoff_targets + delegate_targets

        skill_ctx = await _build_skill_context_for_classify(config, processed_query=processed_query)
        augmented_query = _build_classifier_augmented_query(memory_ctx, harness_ctx, processed_query)
        eq = config.get("_event_queue")
        if skill_ctx.strip() and eq is not None:
            await eq.put(
                AgentEvent(
                    type="skill_context",
                    data={"phase": "classifier", "injected_chars": len(skill_ctx)},
                )
            )
        t_classify = time.perf_counter()
        await _emit_graph_node_event(config, "graph_node_enter", node="classify", input_preview=augmented_query)
        analysis = await _execute_analyze_query(
            config,
            augmented_query=augmented_query,
            skill_context=skill_ctx,
        )
        classify_ms = round((time.perf_counter() - t_classify) * 1000, 1)
        sub_lines = [f"- {st.worker_id}: {st.task}" for st in analysis.subtasks]
        sub_block = "\n".join(sub_lines) if sub_lines else "(none)"
        classify_output = (
            f"pattern={analysis.pattern.value} complexity={analysis.complexity}\n"
            f"reasoning:\n{analysis.reasoning or ''}\n"
            f"subtasks ({len(analysis.subtasks)}):\n{sub_block}"
        )
        classify_step = _make_step(
            StepType.CLASSIFY,
            "analyze_query",
            input=augmented_query,
            output=classify_output,
            max_length=ml,
            duration_ms=classify_ms,
            subtasks=len(analysis.subtasks),
        )
        _steps.append(classify_step)
        if eq is not None:
            await eq.put(
                AgentEvent(
                    type="classify",
                    data={
                        "pattern": analysis.pattern.value,
                        "complexity": analysis.complexity,
                        "reason": analysis.reasoning or "",
                        "output": classify_output,
                        "duration_ms": classify_ms,
                    },
                )
            )
        else:
            await _emit_step_event(config, classify_step)
        await _emit_graph_node_event(
            config,
            "graph_node_exit",
            node="classify",
            duration_ms=round(classify_ms),
        )
        analysis = _coerce_unknown_pattern_handler(config, analysis, registry=registry)
        # In-process fallback when resume runs before a checkpoint exists for this thread.
        config["_last_turn_analysis"] = analysis
        logger.event(
            f"[{name}] classify → pattern={analysis.pattern.value} "
            f"complexity={analysis.complexity} "
            f"subtasks={len(analysis.subtasks)}"
        )
        ms = getattr(analysis, "matched_skill", None)
        logger.debug(
            f"[{name}] classify detail: matched_skill={ms!r} "
            f"reasoning_chars={len(analysis.reasoning or '')} "
            f"direct={'yes' if analysis.direct_response else 'no'}"
        )
        pattern_val = analysis.pattern.value
        handler = None

        if all_delegation_targets:
            _delegate_name = _extract_delegate_from_analysis(analysis, all_delegation_targets)
            if _delegate_name:
                _handoff_target = await resolve_handoff(all_delegation_targets, processed_query, _delegate_name)
                if _handoff_target:
                    logger.event(f"[{name}] handoff → {_handoff_target.name}")
                    handoff_result = await run_delegate(
                        _handoff_target,
                        processed_query,
                        thread_id=effective_thread_id,
                        user_id=user_id,
                        lt_namespace=effective_ltns,
                        context=context,
                    )
                    handoff_result = handoff_result.model_copy(
                        update={
                            "run_id": run_id,
                            "steps": _steps + list(handoff_result.steps),
                            "metadata": {**handoff_result.metadata, "delegated_to": _handoff_target.name},
                        }
                    )
                    await _record_turn(
                        memory, effective_thread_id, raw_query_str, handoff_result, user_id, effective_ltns
                    )
                    return handoff_result

    if cache:
        try:
            from .cache import cache_get

            hit = await cache_get(cache, processed_query, analysis.pattern.value)
            if hit:
                logger.event(f"[{name}] CACHE HIT — returning cached result.")
                cache_step = _make_step(
                    StepType.CACHE_HIT,
                    "semantic_cache",
                    input=processed_query,
                    output=hit["output"],
                    max_length=ml,
                )
                _steps.append(cache_step)
                await _emit_step_event(config, cache_step)
                cached = ExecutionResult(
                    pattern_used=PatternType(hit["pattern"]),
                    query=raw_query_str,
                    output=hit["output"],
                    steps_taken=0,
                    success=True,
                    run_id=run_id,
                    steps=_steps,
                )
                await _record_turn(memory, effective_thread_id, raw_query_str, cached, user_id, effective_ltns)
                return cached
        except Exception as exc:
            logger.warning(f"[{name}] cache_get failed ({exc!r}) — proceeding.")

    if pattern_val in config.get("interrupt_before", []):
        should_continue = await _check_pattern_interrupt(config, "before", pattern_val, raw_query_str)
        if not should_continue:
            int_step = _make_step(
                StepType.INTERRUPT,
                f"interrupt_before:{pattern_val}",
                input=raw_query_str,
                output="aborted",
                max_length=ml,
            )
            _steps.append(int_step)
            await _emit_step_event(config, int_step)
            return ExecutionResult(
                pattern_used=analysis.pattern,
                query=raw_query_str,
                output=f"Aborted by interrupt_before on {pattern_val}.",
                steps_taken=1,
                success=False,
                analysis=analysis,
                run_id=run_id,
                steps=_steps,
            )

    _has_custom_direct = registry.get(PatternType.DIRECT) is not _handle_direct
    _dr = analysis.direct_response
    _direct_text = (
        _dr.strip()
        if isinstance(_dr, str)
        else (str(_dr).strip() if _dr is not None else "")
    )
    # Whitespace-only classifier text must not short-circuit — it would yield an empty AGP assistant
    # message after stripping (``translate`` / wire consumers treat blank as "no output").
    if not is_frozen and analysis.pattern == PatternType.DIRECT and _direct_text and not _has_custom_direct:
        out_blob = f"{analysis.pattern.value}\n{analysis.reasoning or ''}\n{_direct_text}"
        in_tok = _approx_char_tokens(augmented_query)
        out_tok = _approx_char_tokens(out_blob)
        total_tok = in_tok + out_tok
        usage_est = {"input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": total_tok}
        model_lbl = _llm_label(config["llm"])
        direct_step = _make_step(
            StepType.LLM_CALL,
            "direct_shortcircuit",
            input=raw_query_str,
            output=_direct_text,
            max_length=ml,
            usage=usage_est,
            model=model_lbl,
            phase="direct_shortcircuit",
            usage_is_estimate=True,
        )
        _steps.append(direct_step)
        await _emit_step_event(config, direct_step)
        result = ExecutionResult(
            pattern_used=PatternType.DIRECT,
            query=raw_query_str,
            output=_direct_text,
            steps_taken=1,
            success=True,
            analysis=analysis,
            run_id=run_id,
            steps=_steps,
            token_usage=dict(usage_est),
        )

        if pattern_val in config.get("interrupt_after", []):
            should_continue = await _check_pattern_interrupt(config, "after", pattern_val, raw_query_str, result)
            if not should_continue:
                result = ExecutionResult(
                    pattern_used=analysis.pattern,
                    query=raw_query_str,
                    output=(f"Interrupted after {pattern_val}.\nPartial output: {result.output}"),
                    steps_taken=result.steps_taken,
                    success=False,
                    analysis=analysis,
                    worker_results=result.worker_results,
                    run_id=run_id,
                    steps=list(result.steps),
                    token_usage=dict(result.token_usage),
                    messages=list(result.messages),
                )

        result = await _run_after_agent(config.get("middleware", []), result, context)
        await _record_turn(memory, effective_thread_id, raw_query_str, result, user_id, effective_ltns)
        if cache:
            try:
                from .cache import cache_set

                await cache_set(cache, processed_query, pattern_val, result.output)
            except Exception as exc:
                logger.debug(f"[{name}] cache_set (DIRECT) failed: {exc!r}")

        _maybe_fire_feedback_hooks(
            config, result, raw_query_str, name, skill_used=analysis.matched_skill, user_id=user_id
        )

        logger.event(f"[{name}] DIRECT short-circuit — 1 LLM call total.")
        await emit_remaining_token_usage(
            config,
            result.token_usage,
            phase=PatternType.DIRECT.value,
            model=_llm_label(config["llm"]),
        )
        return result

    if not is_frozen:
        handler = registry.get(analysis.pattern)
        if handler is None:
            logger.warning(f"[{name}] No handler for pattern '{pattern_val}' — falling back to REACT.")
            handler = handle_react

    logger.event(f"[{name}] execute → {pattern_val}")
    assert handler is not None, "handler must be set by frozen or dynamic path"
    exec_base = dict(invoke_config or {})
    exec_meta = dict(exec_base.get("metadata") or {})
    exec_meta.setdefault("max_step_output_length", ml)
    exec_base["metadata"] = exec_meta
    exec_invoke_config = {**exec_base, "_steps": _steps}
    t_exec = time.perf_counter()
    await _emit_graph_node_event(config, "graph_node_enter", node=pattern_val, pattern=pattern_val, input_preview=augmented_query)
    handler_user_turn = merge_context_into_user_turn(augmented_query, query)
    from .orchestrator import dispatch_pattern, orchestration_enabled
    from .models import SpawnInstruction

    if orchestration_enabled(config, analysis):
        if isinstance(handler_user_turn, str):
            spawn_task = handler_user_turn
        elif isinstance(handler_user_turn, list):
            spawn_task = text_from_user_turn(handler_user_turn)
        elif isinstance(query, list):
            spawn_task = text_from_user_turn(query)
        else:
            spawn_task = raw_query_str
        instruction = SpawnInstruction(
            pattern=analysis.pattern,
            task=spawn_task,
            system_instruction=str(config.get("system_prompt", "") or ""),
            required_tools=[getattr(t, "name", str(t)) for t in config.get("tools", [])],
            escalation_reason="root_query",
        )
        result = await dispatch_pattern(
            config,
            instruction,
            parent_ctx=None,
            analysis=analysis,
            invoke_config=exec_invoke_config,
            registry=registry,
        )
    else:
        result = await handler(config, handler_user_turn, analysis, exec_invoke_config)
    exec_ms = round((time.perf_counter() - t_exec) * 1000, 1)
    await _emit_graph_node_event(
        config,
        "graph_node_exit",
        node=pattern_val,
        pattern=pattern_val,
        duration_ms=round(exec_ms),
        output_preview=result.output if result.output else None,
        error=None if result.success else "execution failed",
    )
    logger.debug(f"[{name}] pattern execution took {exec_ms}ms")

    if pattern_val in config.get("interrupt_after", []):
        should_continue = await _check_pattern_interrupt(config, "after", pattern_val, raw_query_str, result)
        if not should_continue:
            int_after_step = _make_step(
                StepType.INTERRUPT,
                f"interrupt_after:{pattern_val}",
                input=raw_query_str,
                output="interrupted",
                max_length=ml,
            )
            _steps.append(int_after_step)
            await _emit_step_event(config, int_after_step)
            result = ExecutionResult(
                pattern_used=analysis.pattern,
                query=raw_query_str,
                output=(f"Interrupted after {pattern_val}.\nPartial output: {result.output}"),
                steps_taken=result.steps_taken,
                success=False,
                analysis=analysis,
                worker_results=result.worker_results,
                run_id=run_id,
                steps=_steps,
            )

    result = await _run_after_agent(config.get("middleware", []), result, context)

    result = await _apply_response_format(
        config["llm"],
        result,
        config.get("response_format"),
        llm_timeout=config.get("llm_timeout", 120.0),
        structured_max_retries=config.get("structured_max_retries", 2),
    )

    skill_learner = config.get("skill_learner")
    if skill_learner:
        try:
            skill_learner.maybe_learn(result, query, name, event_queue=config.get("_event_queue"))
        except Exception as exc:
            logger.warning(f"[{name}] skill_learner failed ({exc!r}) — non-fatal.")

    skill_lifecycle = config.get("skill_lifecycle")
    if skill_lifecycle:
        try:
            skill_lifecycle.on_run_complete(
                success=result.success,
                applied_skill=getattr(analysis, "matched_skill", None),
            )
        except Exception as exc:
            logger.warning(f"[{name}] skill_lifecycle failed ({exc!r}) — non-fatal.")

    skill_generator = config.get("skill_generator")
    matched = getattr(analysis, "matched_skill", None)
    if (
        skill_generator
        and not matched
        and result.success
        and analysis.complexity >= 4
        and analysis.pattern != PatternType.DIRECT
        and not is_frozen
    ):
        tools_for_gen = [t for t in config.get("tools", []) if t.name != "load_skill"]
        registry_for_gen = config.get("skill_registry")

        async def _bg_gen() -> None:
            try:
                skill = await skill_generator.generate_for_query(
                    query=processed_query, tools=tools_for_gen, agent_name=name
                )
                if skill and registry_for_gen:
                    await registry_for_gen.save_learned_skill(
                        name=skill.name,
                        description=skill.description,
                        body=skill.body,
                        scope="global",
                        tags=["on-demand", "auto-generated"],
                    )
                    _eq = config.get("_event_queue")
                    if _eq is not None:
                        await _eq.put(
                            AgentEvent(
                                type="skill_learned",
                                data={
                                    "skill_name": skill.name,
                                    "pattern": None,
                                    "scope": "global",
                                    "source": "on_demand",
                                },
                            )
                        )
            except Exception as exc:
                logger.debug(f"[{name}] on-demand skill save failed: {exc!r}")

        from .llm_utils import safe_create_task

        safe_create_task(_bg_gen(), name=f"skill-gen-{name}")

    _maybe_fire_feedback_hooks(
        config, result, raw_query_str, name, skill_used=analysis.matched_skill, user_id=user_id
    )

    for wr in result.worker_results:
        if hasattr(wr, "token_usage") and wr.token_usage:
            _total_usage = _merge_token_usage(_total_usage, wr.token_usage)
    if result.token_usage:
        _total_usage = _merge_token_usage(_total_usage, result.token_usage)

    # Many handlers mutate ``config["_steps"]`` in place and return the same list as ``result.steps``;
    # avoid duplicating that list. Otherwise append handler-only steps not already in the pre-run list.
    if result.steps is _steps:
        all_steps = list(_steps)
    else:
        # Merge by object identity — two distinct steps must not collapse just because Pydantic __eq__ matches.
        _seen_ids = {id(s) for s in _steps}
        _extra: list = []
        for s in result.steps:
            sid = id(s)
            if sid in _seen_ids:
                continue
            _seen_ids.add(sid)
            _extra.append(s)
        all_steps = _steps + _extra

    result = result.model_copy(
        update={
            "run_id": run_id,
            "steps": all_steps,
            "token_usage": _total_usage,
        }
    )
    await _record_turn(memory, effective_thread_id, raw_query_str, result, user_id, effective_ltns)
    if cache and result.success:
        try:
            from .cache import cache_set

            await cache_set(cache, processed_query, pattern_val, result.output)
        except Exception as exc:
            logger.warning(f"[{name}] cache_set failed ({exc!r}) — non-fatal.")

    logger.event(
        f"[{name}] done — run_id={run_id} frozen={is_frozen} success={result.success} output={len(result.output)} chars"
    )
    await emit_remaining_token_usage(
        config,
        _total_usage,
        phase=pattern_val,
        model=_llm_label(config["llm"]),
    )
    return result


def _maybe_fire_feedback_hooks(
    config: dict,
    result: ExecutionResult,
    query: str,
    name: str,
    skill_used: str | None = None,
    *,
    user_id: str | None = None,
) -> None:
    """Fire feedback hooks if configured. Failures are swallowed."""
    if user_id:
        try:
            result.metadata.setdefault("user_id", user_id)
        except Exception:
            pass

    feedback_cfg = config.get("_feedback")
    if not feedback_cfg and not _FEEDBACK_AVAILABLE:
        return

    try:
        run_fresh_feedback_hooks(
            config=feedback_cfg or {},
            result=result,
            query=query,
            skill_used=skill_used,
        )
    except Exception as exc:
        logger.warning(f"[{name}] feedback hooks failed ({exc!r}) — non-fatal.")


class UnifiedAgent:
    """Agent instance produced by ``create_agent`` (Runnable-like API).

    Public entrypoints: ``ainvoke``, ``invoke``, ``astream``, ``astream_events``, ``abatch``.

    Each ``ainvoke`` allocates a new ``signal_queue`` and ``clarification_queues`` in
    ``invoke_config`` so parallel calls do not mix HITL signals.

    Default execution goes through ``run_fresh`` and pattern handlers. A compiled graph
    is created on demand for ``resume``, ``get_state``, and ``get_history`` when a
    ``checkpointer`` is configured.

    ``config["memory"]`` holds session turns; ``config["store"]`` is optional long-term
    storage (skills, feedback, LT memory namespaces).

    ``__init__`` applies one-time LangChain deprecation filtering before LangGraph loads.
    """

    def __init__(self, config: dict) -> None:
        ensure_langchain_pending_deprecation_suppressed()
        self.config = config

    async def __aenter__(self) -> UnifiedAgent:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Release all held resources: MCP connections, thread pools, HTTP clients."""
        if self.config.get("_mcp_client") is not None:
            try:
                await aclose_mcp_client(
                    self.config["_mcp_client"],
                    log_name=self.name,
                    client_holder=self.config.get("_mcp_client_holder"),
                )
            except Exception as exc:
                logger.debug(f"[{self.name}] MCP client cleanup: {exc!r}")
            self.config["_mcp_client"] = None
            self.config["_mcp_connected"] = False
            self.config["_mcp_session_attempted"] = False

        fb = self.config.get("_feedback", {})
        handler = fb.get("handler")
        if handler is not None and hasattr(handler, "aclose"):
            try:
                await handler.aclose()
            except Exception as exc:
                logger.debug(f"[{self.name}] Feedback handler cleanup: {exc!r}")

        mgr = self.config.get("_bg_delegation_manager")
        if isinstance(mgr, BackgroundDelegationManager):
            try:
                await mgr.shutdown(cancel_pending=True)
            except Exception as exc:
                logger.debug(f"[{self.name}] background delegation shutdown: {exc!r}")
            try:
                mgr.cleanup(max_age_seconds=0)
            except Exception as exc:
                logger.debug(f"[{self.name}] background delegation cleanup: {exc!r}")

        _unregister_agent_name(self.name, self.config.get("store"))
        logger.debug(f"[{self.name}] aclose() complete — resources released")

    @property
    def name(self) -> str:
        return self.config["name"]

    def resolve_ids(
        self,
        thread_id: str | None,
        user_id: str | None,
        lt_namespace: tuple | None,
    ) -> tuple[str, tuple, dict]:
        """Compute per-run ids and LangGraph ``invoke_config``.

        Returns ``(effective_thread_id, effective_lt_namespace, invoke_config)``.
        Namespace: ``lt_namespace`` if given, else ``(agent_name, user_id)`` when
        ``user_id`` is set, else ``(agent_name, thread_id)``.

        ``invoke_config["configurable"]`` includes ``thread_id``, ``memory_namespace``,
        ``signal_queue``, and ``clarification_queues`` for this call only.
        """
        effective_thread_id = thread_id or str(uuid.uuid4())
        resolved_user_id = user_id or self.config.get("user_id", "default_user")

        if lt_namespace is not None:
            effective_ltns = lt_namespace
        elif user_id is not None:
            effective_ltns = (self.name, resolved_user_id)
        else:
            effective_ltns = (self.name, effective_thread_id)

        invoke_config = {
            "configurable": {
                "thread_id": effective_thread_id,
                "memory_namespace": effective_ltns,
                "signal_queue": asyncio.Queue(),
                "clarification_queues": {},
            }
        }
        return effective_thread_id, effective_ltns, invoke_config

    @staticmethod
    def _merge_context_into_invoke_config(invoke_config: dict, context: dict | None) -> None:
        """Allow ``ainvoke(..., context={"configurable": {...}})`` to supply a shared ``signal_queue``."""
        if not context:
            return
        extra = context.get("configurable")
        if not isinstance(extra, dict):
            return
        base = invoke_config.setdefault("configurable", {})
        if "signal_queue" in extra:
            base["signal_queue"] = extra["signal_queue"]
        if "clarification_queues" in extra:
            base["clarification_queues"] = extra["clarification_queues"]

    async def ainvoke(
        self,
        query: str | dict | list,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
    ) -> ExecutionResult:
        """Run a single agent turn and return ``ExecutionResult`` (includes ``run_id`` for ``feedback``).

        ``query`` is normally a string. A ``dict`` is allowed only for frozen agents and
        must contain every ``input_key`` field. A ``list`` of OpenAI-style content blocks
        is allowed when ``frozen=False`` (multimodal user turns).

        Raises:
            ValueError: dict ``query`` with ``frozen=False``, or missing frozen input keys.
        """
        if isinstance(query, list) and self.config.get("frozen"):
            raise ValueError("list / multimodal user turns are not supported when frozen=True.")
        if isinstance(query, dict):
            if not self.config.get("frozen"):
                raise ValueError(
                    "dict queries are only supported when frozen=True. "
                    "Pass a plain str, or create the agent with "
                    "frozen=True and input_key=['key1', 'key2']."
                )
            keys = self.config.get("input_key", "input")
            required = [keys] if isinstance(keys, str) else list(keys)
            missing = [k for k in required if k not in query]
            if missing:
                raise ValueError(
                    f"Frozen agent with input_key={required!r}: "
                    f"missing keys in query dict: {missing}. "
                    f"Provide all keys: {required}."
                )

        effective_thread_id, effective_ltns, invoke_config = self.resolve_ids(thread_id, user_id, lt_namespace)
        self._merge_context_into_invoke_config(invoke_config, context)

        await _ensure_mcp_connected(self.config)
        await _ensure_skills_bootstrapped(self.config)
        await _ensure_harness_bootstrapped(
            self.config,
            effective_thread_id,
            effective_ltns,
            _wire_query_snapshot(query),
        )

        if self.config.get("frozen"):
            await _ensure_frozen_analysis(self.config)

        run_config = {
            **self.config,
            "signal_queue": invoke_config["configurable"]["signal_queue"],
            "clarification_queues": invoke_config["configurable"]["clarification_queues"],
        }

        result = await run_fresh(
            config=run_config,
            query=query,
            effective_thread_id=effective_thread_id,
            effective_ltns=effective_ltns,
            invoke_config=invoke_config,
            context=context or {},
            user_id=user_id,
        )

        await _save_checkpoint(
            self.config.get("checkpointer"),
            effective_thread_id,
            result,
            _wire_query_snapshot(query),
        )

        return result

    async def astream(
        self,
        query: str | dict | list,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
        stream_mode: str = "tokens",
    ) -> AsyncGenerator[Any, None]:
        """Stream output chunks.

        ``stream_mode="tokens"``
            * **DIRECT pattern** (non-frozen, single-LLM call): yields real LLM
              token strings as they arrive from the model, giving true streaming
              latency. This path **does not** run the full ``run_fresh`` pipeline:
              semantic cache read/write, session checkpoint persistence,
              ``_record_turn`` / session transcript, and feedback hooks run only on the
              :meth:`ainvoke` / ``stream_mode="result"`` path (or after you call
              :meth:`ainvoke` yourself). Prefer :meth:`astream_events` if you need AGP
              parity (tokens + ``done`` with a persisted turn).
            * **All other patterns** (SUPERVISOR, SEQUENTIAL, REFLECTION, …):
              ``ainvoke`` is called first and the final answer is then yielded
              word-by-word via ``asyncio.sleep(0)``.  This is *simulated*
              streaming — useful for consistent API shape but **not** true
              token-level streaming.  For real token deltas from multi-agent
              patterns use :meth:`astream_events` and listen for
              ``token.delta`` AGP events.

        ``stream_mode="result"``
            Yields a single :class:`ExecutionResult` after the invocation
            completes, regardless of pattern.
        """
        if stream_mode == "tokens" and isinstance(query, str) and not self.config.get("frozen"):
            streamed = await self._try_direct_stream(
                query, thread_id=thread_id, user_id=user_id, lt_namespace=lt_namespace, context=context
            )
            if streamed is not None:
                async for chunk in streamed:
                    yield chunk
                return

        result = await self.ainvoke(
            query,
            thread_id=thread_id,
            user_id=user_id,
            lt_namespace=lt_namespace,
            context=context,
        )

        if stream_mode == "result":
            yield result
            return

        # Simulated streaming: preserve whitespace, tabs, and blank lines (``split(" ")`` does not).
        out = result.output
        if not out:
            return
        chunk = max(1, int(self.config.get("simulated_stream_chunk_chars", 12)))
        for i in range(0, len(out), chunk):
            yield out[i : i + chunk]
            await asyncio.sleep(0)

    async def _try_direct_stream(
        self,
        query: str,
        *,
        thread_id: str | None,
        user_id: str | None,
        lt_namespace: tuple | None,
        context: dict | None,
    ) -> AsyncGenerator[str, None] | None:
        """If classification is DIRECT, return an LLM token stream; else ``None``."""
        try:
            await _ensure_mcp_connected(self.config)
            await _ensure_skills_bootstrapped(self.config)

            effective_thread_id, effective_ltns, _inv = self.resolve_ids(thread_id, user_id, lt_namespace)
            await _ensure_harness_bootstrapped(
                self.config,
                effective_thread_id,
                effective_ltns,
                _wire_query_snapshot(query),
            )
            ctx = context or {}

            raw_query_str = query
            processed_query = await _run_before_agent(self.config.get("middleware", []), raw_query_str, ctx)

            cfg = await _resolve_system_prompt_for_turn(
                self.config,
                raw_query_str=raw_query_str,
                context=ctx,
                thread_id=effective_thread_id,
                user_id=user_id,
            )
            resolved_sp = cfg["system_prompt"]

            memory = cfg.get("memory")
            store = cfg.get("store")
            memory_ctx = await build_memory_context(
                session=memory,
                store=store,
                thread_id=effective_thread_id,
                namespace=effective_ltns,
                query=processed_query,
                last_n=_memory_injection_last_n(cfg),
            )

            harness_ctx = await _build_harness_context_for_classify(cfg, is_frozen=False)
            skill_ctx = await _build_skill_context_for_classify(cfg, processed_query=processed_query)
            augmented_query = _build_classifier_augmented_query(memory_ctx, harness_ctx, processed_query)
            analysis = await _execute_analyze_query(
                cfg,
                augmented_query=augmented_query,
                skill_context=skill_ctx,
            )

            if analysis.pattern != PatternType.DIRECT:
                return None

            if analysis.pattern.value in self.config.get("interrupt_before", []):
                return None

            async def _stream_direct() -> AsyncGenerator[str, None]:
                llm = self.config["llm"]
                messages = [SystemMessage(content=resolved_sp), HumanMessage(content=query)]
                timeout_s = float(self.config.get("llm_timeout", 120.0))
                deadline = time.monotonic() + timeout_s

                agen = llm.astream(messages)
                aiter = agen.__aiter__()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"Direct stream timed out after {timeout_s} seconds.")
                    try:
                        chunk = await asyncio.wait_for(aiter.__anext__(), timeout=remaining)
                    except StopAsyncIteration:
                        return
                    content = chunk.content
                    if content:
                        yield content if isinstance(content, str) else str(content)

            return _stream_direct()
        except Exception as exc:
            if isinstance(exc, MCPConnectionError):
                raise
            logger.debug(f"[astream] direct stream attempt failed: {exc!r} — falling back to ainvoke")
            return None

    async def abatch(
        self,
        queries: list[str | dict],
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
        max_concurrent: int = 5,
    ) -> list[ExecutionResult]:
        """Concurrent ``ainvoke`` for each query, bounded by ``max_concurrent``.

        Each query runs in its **own isolated thread** so that LangGraph
        checkpoints never collide.  If ``thread_id`` is supplied it is used as
        a *prefix* — the final thread for query *i* becomes
        ``"{thread_id}_batch_{i}"``.  This preserves the ability to resume a
        batch run while preventing cross-query state leakage.
        """
        from uuid import uuid4 as _uuid4

        sem = asyncio.Semaphore(max_concurrent)

        async def _run_one(q: str | dict, idx: int) -> ExecutionResult:
            per_query_thread = (
                f"{thread_id}_batch_{idx}" if thread_id else f"batch_{_uuid4().hex[:12]}"
            )
            async with sem:
                return await self.ainvoke(
                    q,
                    thread_id=per_query_thread,
                    user_id=user_id,
                    lt_namespace=lt_namespace,
                    context=context,
                )

        return list(await asyncio.gather(*[_run_one(q, i) for i, q in enumerate(queries)]))

    async def astream_events(
        self,
        query: str | dict | list,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Stream structured events for UI instrumentation.

        Events are emitted during ``run_fresh`` (e.g. ``thinking``, ``llm_call``,
        ``tool_call``, ``tool_result``, ``token``, worker events). The stream ends
        with ``done`` (payload includes serialized result) or ``error``.
        """
        event_queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def _run_and_push() -> None:
            try:
                effective_thread_id, effective_ltns, invoke_config = self.resolve_ids(thread_id, user_id, lt_namespace)
                self._merge_context_into_invoke_config(invoke_config, context)

                await _ensure_mcp_connected(self.config)
                await _ensure_skills_bootstrapped(self.config, event_queue=event_queue)

                if self.config.get("frozen"):
                    await _ensure_frozen_analysis(self.config)

                run_config = {
                    **self.config,
                    "signal_queue": invoke_config["configurable"]["signal_queue"],
                    "clarification_queues": invoke_config["configurable"]["clarification_queues"],
                    "_event_queue": event_queue,
                }

                result = await run_fresh(
                    config=run_config,
                    query=query,
                    effective_thread_id=effective_thread_id,
                    effective_ltns=effective_ltns,
                    invoke_config=invoke_config,
                    context=context or {},
                    user_id=user_id,
                )

                await _save_checkpoint(
                    self.config.get("checkpointer"),
                    effective_thread_id,
                    result,
                    _wire_query_snapshot(query),
                )

                await event_queue.put(
                    AgentEvent(
                        type="done",
                        data={"result": execution_result_wire_dict(result)},
                    )
                )
            except Exception as exc:
                await event_queue.put(
                    AgentEvent(
                        type="error",
                        data={"error": str(exc)},
                    )
                )
            finally:
                await event_queue.put(None)

        task = asyncio.create_task(_run_and_push())
        try:
            while True:
                if task.done() and event_queue.empty():
                    break
                event = await event_queue.get()
                if event is None:
                    break
                yield event
        finally:
            with contextlib.suppress(asyncio.QueueFull):
                event_queue.put_nowait(None)
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            elif not task.cancelled():
                exc = task.exception()
                if exc is not None:
                    raise exc

    async def astream_agp_events(
        self,
        query: str | dict | list,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
        session_id: str | None = None,
    ) -> AsyncGenerator[Any, None]:
        """Stream typed AGP :class:`~agloom.protocol.Envelope` events.

        This is the **unified** streaming path — the same event objects that
        ``agloom.runtime`` writes to the AGP wire are now delivered directly to
        in-process consumers (CLI, TUI, tests) without going through JSON
        serialisation.  Every ``AgentEvent`` emitted by the execution engine is
        translated via :func:`agloom.runtime.translator.translate` before being
        yielded, so callers receive fully-typed Pydantic instances (``TokenDelta``,
        ``WorkerSpawned``, ``MetricTokens``, …) rather than loose ``{type, data}``
        dicts.

        The stream always starts with ``session.opened`` and ends with
        ``session.closed`` so consumers can treat it as a self-contained AGP
        session without needing a separate ``SessionEmitter``.

        Example::

            async for evt in agent.astream_agp_events("Read pyproject.toml"):
                if evt.type == "token.delta":
                    print(evt.data.text, end="", flush=True)
                elif evt.type == "worker.spawned":
                    print(f"[worker] {evt.data.worker_id}: {evt.data.task}")
                elif evt.type == "metric.tokens":
                    print(f"tokens: {evt.data.input_tokens}↑ {evt.data.output_tokens}↓")
        """
        from uuid import uuid4 as _uuid4

        from .protocol import SessionEmitter
        from .runtime.translator import translate

        eff_session = session_id or f"sess_{_uuid4().hex[:16]}"
        eff_thread = thread_id or f"thread_{_uuid4().hex[:16]}"

        # Collect AGP Envelope objects via on_emit (no JSON written — callback-only mode).
        agp_queue: asyncio.Queue[Any] = asyncio.Queue()

        def _on_emit(evt: Any) -> None:
            agp_queue.put_nowait(evt)

        emitter = SessionEmitter.for_callback_only(
            session=eff_session,
            thread=eff_thread,
            on_emit=_on_emit,
        )
        emitter.open()

        async def _translate_stream() -> None:
            try:
                async for agent_event in self.astream_events(
                    query,
                    thread_id=thread_id,
                    user_id=user_id,
                    lt_namespace=lt_namespace,
                    context=context,
                ):
                    translate(agent_event, emitter)
            except asyncio.CancelledError:
                emitter.close(reason="user_aborted")
                raise
            except Exception as exc:
                emitter.emit_error(
                    severity="fatal",
                    message=str(exc).strip() or repr(exc),
                    error_class=type(exc).__name__,
                    stage="invocation",
                )
                emitter.close(reason="error")
                agp_queue.put_nowait(None)  # sentinel — must send even on error
                return
            emitter.close(reason="completed")
            agp_queue.put_nowait(None)  # sentinel

        task = asyncio.create_task(_translate_stream())

        try:
            while True:
                item = await agp_queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                raise exc

    def invoke(
        self,
        query: str | dict,
        **kwargs,
    ) -> ExecutionResult:
        """Synchronous ``ainvoke``. Uses ``asyncio.run`` when no loop is running; otherwise runs in a worker thread."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            return asyncio.run(self.ainvoke(query, **kwargs))

        future = _sync_bridge_executor().submit(_run_coroutine_in_new_loop, self.ainvoke(query, **kwargs))
        return future.result()

    async def feedback(
        self,
        run_id: str,
        rating: str,  # "positive" | "negative" | "neutral"
        *,
        comment: str = "",
        correct: str | None = None,  # correction text when rating="negative"
        metadata: dict | None = None,
    ) -> None:
        """Attach user feedback to a completed run (``rating``: positive / negative / neutral).

        No-op if ``create_agent`` was called without ``store`` (feedback system disabled).
        """
        feedback_cfg = self.config.get("_feedback")
        if not feedback_cfg:
            logger.debug(
                f"[{self.name}] feedback() called but no feedback system configured "
                f"(pass store= to create_agent to enable). Skipping."
            )
            return

        try:
            await apply_user_feedback(
                config=feedback_cfg,
                run_id=run_id,
                rating=rating,
                comment=comment,
                correct=correct or "",
                metadata=metadata or {},
            )
            logger.event(
                f"[{self.name}] feedback recorded — run_id={run_id} "
                f"rating={rating}" + (f" correction={correct[:60]!r}" if correct else "")
            )
        except Exception as exc:
            logger.warning(f"[{self.name}] feedback() failed ({exc!r}) — non-fatal.")

    async def resume(
        self,
        value: Any,
        thread_id: str,
        invoke_config: dict | None = None,
        effective_ltns: tuple = (),
    ) -> ExecutionResult:
        """Resume graph execution after an interrupt using LangGraph ``Command(resume=value)``.

        Unlike ``ainvoke`` (``run_fresh``), this targets the compiled graph. Requires a
        ``checkpointer`` passed to ``create_agent``.

        Before invoking the graph, restores ``analysis`` (and ``query`` when present) from the
        latest checkpoint or ``config["_last_turn_analysis"]`` so the classify node does not
        re-run and change the selected pattern mid-interrupt.
        """
        from langgraph.types import Command

        if self.config.get("checkpointer") is None:
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=str(value),
                output=(
                    "Resume requires a checkpointer. "
                    "Pass checkpointer=InMemorySaver() to create_agent()."
                ),
                steps_taken=1,
                success=False,
            )

        compiled = self.config.get("compiled_graph")
        if compiled is None:
            from .graph import build_agent_graph

            compiled = build_agent_graph(self.config)
            self.config["compiled_graph"] = compiled

        memory = self.config.get("memory")
        logger.event(f"[{self.name}] resume: thread={thread_id} value={str(value)[:60]}")
        try:
            cfg = invoke_config or {"configurable": {"thread_id": thread_id}}
            ckpt = await self.get_state(thread_id)
            preserved_analysis = _analysis_from_checkpointer_tuple(ckpt)
            if preserved_analysis is None:
                preserved_analysis = self.config.get("_last_turn_analysis")
            resume_query: str | None = None
            if ckpt is not None:
                try:
                    ck = getattr(ckpt, "checkpoint", None)
                    if isinstance(ck, dict):
                        cv = ck.get("channel_values")
                        if isinstance(cv, dict):
                            q = cv.get("query")
                            if isinstance(q, str) and q.strip():
                                resume_query = q
                except Exception:
                    pass
            await _seed_graph_state_for_resume(
                compiled,
                cfg,
                analysis=preserved_analysis,
                query=resume_query,
            )
            if preserved_analysis is not None:
                logger.debug(
                    f"[{self.name}] resume: reusing analysis pattern={preserved_analysis.pattern.value}"
                )
            state = await cast(Any, compiled).ainvoke(
                Command(resume=value),
                config=cfg,
            )
            result = state.get("result")
            if result:
                await _record_turn(
                    memory,
                    thread_id,
                    f"RESUME: {value!r}",
                    result,
                    None,
                    effective_ltns,
                )
                return result
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=str(value),
                output="Resume completed but no result in graph state.",
                steps_taken=1,
                success=False,
            )
        except Exception as exc:
            logger.error(f"[{self.name}] resume failed: {exc!r}")
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=str(value),
                output=f"Resume failed: {exc}",
                steps_taken=1,
                success=False,
            )

    async def get_state(self, thread_id: str) -> Any:
        """Return the latest checkpoint tuple for ``thread_id``, or ``None`` if missing.

        Raises:
            RuntimeError: if no ``checkpointer`` was configured.
        """
        checkpointer = self.config.get("checkpointer")
        if not checkpointer:
            raise RuntimeError(
                "get_state() requires a checkpointer. Pass checkpointer=MemorySaver() to create_agent()."
            )
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        try:
            if hasattr(checkpointer, "aget_tuple"):
                return await checkpointer.aget_tuple(config)
            if hasattr(checkpointer, "get_tuple"):
                return checkpointer.get_tuple(config)
        except Exception as exc:
            logger.warning(f"get_state failed ({exc!r}) — returning None.")
        return None

    async def get_history(self, thread_id: str) -> Any:
        """Return an async iterator (or sync list) of checkpoints for ``thread_id``.

        Raises:
            RuntimeError: if no ``checkpointer`` was configured.
        """
        checkpointer = self.config.get("checkpointer")
        if not checkpointer:
            raise RuntimeError(
                "get_history() requires a checkpointer. Pass checkpointer=MemorySaver() to create_agent()."
            )
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        if hasattr(checkpointer, "alist"):
            return checkpointer.alist(config)
        if hasattr(checkpointer, "list"):
            return checkpointer.list(config)
        return None

    def register_pattern(
        self,
        pattern_type: PatternType,
        handler_fn: Callable,
    ) -> None:
        """Override the handler for ``pattern_type`` on this agent instance (takes effect on next call)."""
        self.config["registry"][pattern_type] = handler_fn
        logger.event(f"[{self.name}] Pattern registered: {pattern_type.value}")

    def as_tool(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> BaseTool:
        """Expose this agent as a LangChain tool (delegates to ``make_agent_tool``)."""
        return make_agent_tool(self, name=name, description=description)

    def register_handoff(
        self,
        target: Any,
        *,
        name: str | None = None,
        description: str = "",
        filter_fn: Callable | None = None,
        input_transform: Callable | None = None,
    ) -> None:
        """Register a delegate the classifier may route to (append-only list on ``_handoff_targets``)."""
        if isinstance(target, HandoffTarget):
            ht = target
        else:
            ht = HandoffTarget(
                target,
                name=name,
                description=description,
                filter_fn=filter_fn,
                input_transform=input_transform,
            )
        self.config.setdefault("_handoff_targets", []).append(ht)
        logger.event(f"[{self.name}] Handoff registered: {ht.name!r} — {ht.description[:60]}")

    async def adelegate(
        self,
        query: str,
        *,
        delegate_name: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
    ) -> ExecutionResult:
        """Delegate ``query`` to a matching handoff/delegate target and await its result.

        Raises:
            ValueError: No target matches ``delegate_name`` (if given) or filters.
        """
        all_targets = self._all_delegation_targets()
        target = await resolve_handoff(all_targets, query, delegate_name)
        if target is None:
            available = [t.name for t in all_targets]
            raise ValueError(
                "No matching delegate found"
                + (f" for name={delegate_name!r}" if delegate_name else "")
                + f". Available: {available}"
            )
        return await run_delegate(
            target,
            query,
            thread_id=thread_id,
            user_id=user_id,
            lt_namespace=lt_namespace,
            context=context,
        )

    async def adelegate_background(
        self,
        query: str,
        *,
        delegate_name: str | None = None,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
    ) -> str:
        """Start delegation in the background; return id for ``await_background`` / ``cancel_background``."""
        all_targets = self._all_delegation_targets()
        target = await resolve_handoff(all_targets, query, delegate_name)
        if target is None:
            available = [t.name for t in all_targets]
            raise ValueError(
                "No matching delegate found"
                + (f" for name={delegate_name!r}" if delegate_name else "")
                + f". Available: {available}"
            )
        mgr: BackgroundDelegationManager = self.config["_bg_delegation_manager"]
        return await mgr.submit(
            target,
            query,
            thread_id=thread_id,
            user_id=user_id,
            lt_namespace=lt_namespace,
            context=context,
        )

    async def await_background(
        self,
        task_id: str,
        *,
        timeout: float | None = None,
    ) -> ExecutionResult | None:
        """Block until the background task completes (see ``BackgroundDelegationManager.await_result``)."""
        mgr: BackgroundDelegationManager = self.config["_bg_delegation_manager"]
        return await mgr.await_result(task_id, timeout=timeout)

    def background_status(self, task_id: str):
        """Get status of a background delegation task."""
        mgr: BackgroundDelegationManager = self.config["_bg_delegation_manager"]
        return mgr.status(task_id)

    async def cancel_background(self, task_id: str) -> bool:
        """Cancel a running background delegation. Returns True if cancelled."""
        mgr: BackgroundDelegationManager = self.config["_bg_delegation_manager"]
        return await mgr.cancel(task_id)

    def _all_delegation_targets(self) -> list:
        """Collect all delegation targets: handoff targets + delegates."""
        targets = list(self.config.get("_handoff_targets") or [])
        targets.extend(self.config.get("_delegate_targets") or [])
        return targets

    def __repr__(self) -> str:
        cfg = self.config
        underlying = getattr(cfg.get("llm"), "bound", cfg.get("llm"))
        model_cls = type(underlying).__name__ if underlying else "None"
        has_feedback = bool(cfg.get("_feedback"))
        frozen_str = f", frozen=True(input_key={cfg.get('input_key')!r})" if cfg.get("frozen") else ""
        return (
            f"UnifiedAgent("
            f"name={cfg['name']!r}, "
            f"model={model_cls}, "
            f"tools={[t.name for t in cfg.get('tools', [])]}, "
            f"patterns={[p.value for p in cfg.get('registry', {})]}{frozen_str}, "
            f"feedback={'on' if has_feedback else 'off'}"
            f")"
        )


async def create_agent(
    model: Any,
    tools: Sequence[Any] | None = None,
    system_prompt: Any = None,
    middleware: Sequence[Any] = (),
    response_format: Any = None,
    state_schema: type | None = None,
    context_schema: type | None = None,
    checkpointer: Any = None,
    store: Any = None,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    debug: bool = False,
    name: str | None = None,
    query_cache: Any = None,
    memory: SessionMemory | None = None,
    enable_memory_tools: bool = True,
    interrupt_before_tools: list[str] | None = None,
    interrupt_before_workers: list[str] | None = None,
    interrupt_after_workers: list[str] | None = None,
    user_callback: Callable | None = None,
    user_id: str | None = None,
    max_concurrent: int = 4,
    max_retries: int = 2,
    retry_delay: float = 1.0,
    llm_timeout: float = 120.0,
    classifier_timeout: float = 60.0,
    structured_max_retries: int = 2,
    rate_limit: float | None = None,
    low_score_threshold: float = 0.40,
    review_every_n_runs: int = 25,
    trend_every_n_runs: int = 100,
    max_skills: int = 30,
    session_max_turns: int = 50,
    max_reflection_iterations: int = 3,
    reflection_threshold: int = 7,
    mcp_servers: list[MCPServerConfig] | None = None,
    max_step_output_length: int = 0,
    fallback_pattern: PatternType | None = None,
    auto_summarize: bool = True,
    summarize_threshold: int = 200_000,
    summarize_max_tokens_budget: int | None = None,
    summarizer_model: Any = None,
    feedback_handler: Any | None = None,
    delegates: Sequence[Any] | None = None,
    frozen: bool = False,
    frozen_template: str | None = None,
    input_key: str | list[str] = "input",
    frozen_analysis_ttl: float = 0,
    harness: bool = False,
    harness_project_name: str = "project",
    cli_tools: bool | dict[str, Any] | None = None,
    require_tool_approval_for_cli_tools: bool = True,
    skills_disk_mirror: Path | str | None = None,
    react_force_tool_choice_on_user_turn: bool = True,
    react_tool_use_failed_auto_retries_hitl: int = 2,
    react_tool_use_failed_user_rounds: int = 3,
    max_pattern_depth: int = 0,
    max_orchestration_llm_calls: int = 100,
    max_orchestration_tokens: int = 0,
    enable_auto_escalation: bool = False,
    orchestration_plan_from_classifier: bool = True,
    escalation_rules: list[str] | None = None,
    enable_pattern_spawns: bool = True,
    enable_orchestration_llm_eval: bool = True,
    enable_dynamic_dag_nodes: bool = True,
    enable_supervisor_worker_dispatch: bool = True,
    orchestration_evaluation_llm: Any = None,
) -> UnifiedAgent:
    """Construct a configured ``UnifiedAgent`` (async).

    Kwargs are validated via ``models.AgentConfig`` before wiring. Important combinations:

    ``store``: LT memory tools, skill registry, feedback (when enabled).
    ``frozen`` and ``frozen_template``: one-time classification; dict ``query`` must match ``input_key``.
    ``harness`` with ``store``: adds progress/git tools; ignored without ``store``.
    ``query_cache``: ``None`` (default) enables an in-memory semantic cache (see
    :func:`agloom.cache.default_query_cache`). Pass ``False`` to disable caching entirely, or pass
    the dict returned by :func:`agloom.cache.create_cache` for custom embeddings / Qdrant.
    ``checkpointer``: enables ``get_state``, ``get_history``, ``resume``.
    ``mcp_servers``: lazy MCP connect on first ``ainvoke``.
    ``react_force_tool_choice_on_user_turn``: when True (default), ReAct uses LangChain
    ``tool_choice=required`` after each user message so providers like Groq must emit a
    structured tool call instead of prose (avoids ``tool_use_failed``).

    Also registers the agent name against the store for duplicate-name warnings and may
    extend ``tools`` (memory load_skill, harness tools).
    """
    configure_package_logging(debug)

    from .cli_tools import CLI_TOOLS_SYSTEM_APPENDIX, get_cli_tools, normalize_cli_tools_kwargs

    cli_tools_kw = normalize_cli_tools_kwargs(cli_tools)
    ibi_merged = list(interrupt_before_tools or [])
    # Built-in CLI tools + HITL: when ``require_tool_approval_for_cli_tools`` and ``user_callback``
    # are set, use the ``"tools"`` wildcard so every bundled CLI tool pauses for approval (CLI default).
    # Otherwise keep granular interrupts (destructive FS + shell) so library/tests without a callback
    # still get conservative gates.
    if cli_tools_kw and "tools" not in ibi_merged:
        if require_tool_approval_for_cli_tools and user_callback:
            ibi_merged.insert(0, "tools")
        else:
            from .cli_tools.safety_metadata import tools_hitl_granular_interrupt

            for token in tools_hitl_granular_interrupt(
                allow_shell=bool(cli_tools_kw.get("allow_shell", True)),
            ):
                if token not in ibi_merged:
                    ibi_merged.append(token)

    resolved_query_cache: Any = query_cache
    if resolved_query_cache is None:
        try:
            from .cache import default_query_cache as _default_query_cache

            resolved_query_cache = _default_query_cache()
        except Exception as exc:
            logger.warning(
                f"Default semantic query cache unavailable ({exc!r}); continuing without cache. "
                "Pass query_cache=False to disable this message, or pass create_cache(...) explicitly."
            )
            resolved_query_cache = None

    AgentConfig(
        model=model,
        name=name or "UnifiedAgent",
        tools=list(tools or []),
        system_prompt=system_prompt,
        middleware=middleware,
        response_format=response_format,
        state_schema=state_schema,
        context_schema=context_schema,
        checkpointer=checkpointer,
        store=store,
        memory=memory,
        enable_memory_tools=enable_memory_tools,
        query_cache=resolved_query_cache,
        interrupt_before=interrupt_before or [],
        interrupt_after=interrupt_after or [],
        interrupt_before_tools=ibi_merged,
        interrupt_before_workers=interrupt_before_workers or [],
        interrupt_after_workers=interrupt_after_workers or [],
        user_callback=user_callback,
        debug=debug,
        max_concurrent=max_concurrent,
        max_retries=max_retries,
        retry_delay=retry_delay,
        llm_timeout=llm_timeout,
        classifier_timeout=classifier_timeout,
        structured_max_retries=structured_max_retries,
        rate_limit=rate_limit,
        low_score_threshold=low_score_threshold,
        review_every_n_runs=review_every_n_runs,
        trend_every_n_runs=trend_every_n_runs,
        max_skills=max_skills,
        user_id=user_id,
        session_max_turns=session_max_turns,
        max_reflection_iterations=max_reflection_iterations,
        reflection_threshold=reflection_threshold,
        mcp_servers=list(mcp_servers or []),
        react_force_tool_choice_on_user_turn=react_force_tool_choice_on_user_turn,
        react_tool_use_failed_auto_retries_hitl=react_tool_use_failed_auto_retries_hitl,
        react_tool_use_failed_user_rounds=react_tool_use_failed_user_rounds,
        max_pattern_depth=max_pattern_depth,
        max_orchestration_llm_calls=max_orchestration_llm_calls,
        max_orchestration_tokens=max_orchestration_tokens,
        enable_auto_escalation=enable_auto_escalation,
        orchestration_plan_from_classifier=orchestration_plan_from_classifier,
        escalation_rules=escalation_rules or ["default"],
        enable_pattern_spawns=enable_pattern_spawns,
        enable_orchestration_llm_eval=enable_orchestration_llm_eval,
        enable_dynamic_dag_nodes=enable_dynamic_dag_nodes,
        enable_supervisor_worker_dispatch=enable_supervisor_worker_dispatch,
        orchestration_evaluation_llm=orchestration_evaluation_llm,
        auto_summarize=auto_summarize,
        summarize_threshold=summarize_threshold,
        summarize_max_tokens_budget=summarize_max_tokens_budget,
        summarizer_model=summarizer_model,
    )

    _validate_frozen_params(frozen, frozen_template, input_key)

    skills_mirror_path: Path | None = Path(skills_disk_mirror).resolve() if skills_disk_mirror is not None else None

    resolved_llm = resolve_model(model)
    resolved_prompt = resolve_system_prompt(system_prompt)
    agent_name = (name or "UnifiedAgent").strip()
    resolved_tools = normalize_tools(tools or [])
    _check_reserved_tool_names(resolved_tools)
    _task_agent_cell: list[Any | None] | None = None
    if cli_tools_kw is not None and bool(cli_tools_kw.get("task_tool", True)):
        _task_agent_cell = [None]
    if cli_tools_kw is not None:
        builtins = get_cli_tools(
            working_dir=cli_tools_kw["working_dir"],
            allow_shell=bool(cli_tools_kw.get("allow_shell", True)),
            allow_network=bool(cli_tools_kw.get("allow_network", True)),
            sandbox=bool(cli_tools_kw.get("sandbox", True)),
            task_agent_cell=_task_agent_cell,
        )
        builtins_by_name = {t.name: t for t in builtins}
        merged = OrderedDict((t.name, t) for t in builtins)
        for t in resolved_tools:
            merged[t.name] = t
        resolved_tools = list(merged.values())
        builtins_still_present = any(merged[n] is builtins_by_name[n] for n in builtins_by_name)
        if isinstance(resolved_prompt, str) and builtins_still_present:
            resolved_prompt = resolved_prompt.rstrip() + CLI_TOOLS_SYSTEM_APPENDIX

    resolved_store: LongTermStore | None = None
    if store is not None:
        resolved_store = store if isinstance(store, LongTermStore) else LongTermStore(store=store)

    _register_agent_name(agent_name, resolved_store)

    if resolved_store is not None and enable_memory_tools:
        try:
            mem_tools = create_memory_tools(resolved_store)
            resolved_tools = mem_tools + resolved_tools  # memory tools first
        except Exception as exc:
            logger.warning(f"[{agent_name}] Failed to create memory tools ({exc!r}) — continuing without.")

    resolved_summarizer = resolve_model(summarizer_model) if summarizer_model else resolved_llm
    memory_budget = summarize_max_tokens_budget
    if memory_budget is None:
        memory_budget = _max_tokens_budget_from_chat_model(resolved_llm)
    resolved_memory = memory
    if resolved_memory is None:
        try:
            from langgraph.store.memory import InMemoryStore as LGStore

            resolved_memory = SessionMemory(
                store=LGStore(),
                max_turns=session_max_turns,
                auto_summarize=auto_summarize,
                summarize_threshold=summarize_threshold,
                summarize_max_tokens_budget=memory_budget,
                summarizer_model=resolved_summarizer if auto_summarize else None,
            )
        except ImportError:
            resolved_memory = SessionMemory(
                max_turns=session_max_turns,
                auto_summarize=auto_summarize,
                summarize_threshold=summarize_threshold,
                summarize_max_tokens_budget=memory_budget,
                summarizer_model=resolved_summarizer if auto_summarize else None,
            )
        logger.debug(
            f"{agent_name}: SessionMemory auto-created with ephemeral InMemoryStore. "
            f"auto_summarize={auto_summarize} threshold={summarize_threshold} "
            f"summarize_max_tokens_budget={memory_budget!r} "
            f"For persistence: memory=SessionMemory(store=AsyncSqliteStore(...))"
        )
    elif auto_summarize and resolved_memory.summarizer_model is None:
        resolved_memory.summarizer_model = resolved_summarizer
    if (
        memory_budget is not None
        and isinstance(resolved_memory, SessionMemory)
        and getattr(resolved_memory, "summarize_max_tokens_budget", None) is None
    ):
        resolved_memory.summarize_max_tokens_budget = memory_budget

    _harness_enabled = False
    _git_session: Any = None
    _progress_tracker_factory: Callable | None = None
    _harness_progress_tracker: Any = None

    if harness and resolved_store is not None and _HARNESS_AVAILABLE:
        _harness_enabled = True
        assert GitSession is not None
        assert create_initializer_tool is not None
        _git_session = GitSession()
        # Progress tool factories require a tracker instance; await singleton creation here
        # (create_agent is async — safe). Without this, ``bootstrap_progress_tool()`` etc.
        # raised TypeError (missing ``tracker``).
        _aw_get_pt = cast(
            "Callable[[Any, str, str], Awaitable[Any]]",
            get_progress_tracker,
        )
        _harness_progress_tracker = await _aw_get_pt(
            resolved_store, agent_name, harness_project_name
        )

        def _progress_tracker_factory() -> Any:
            return get_progress_tracker(resolved_store, agent_name, harness_project_name)

        def _make_tool(factory_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            fn = factory_fn(*args, **kwargs)
            tool_name = getattr(fn, "__name__", factory_fn.__name__.replace("_tool", ""))
            try:
                return StructuredTool.from_function(
                    fn,
                    name=tool_name,
                    description=fn.__doc__ or "",
                )
            except Exception as exc:
                logger.warning(
                    f"{agent_name}: harness tool {tool_name!r} could not be wrapped as StructuredTool "
                    f"({exc!r})"
                )
                raise

        harness_tools = [
            _make_tool(git_status_tool, _git_session),
            _make_tool(git_log_tool, _git_session),
            _make_tool(git_commit_tool, _git_session),
            _make_tool(git_checkpoint_tool, _git_session, session_id=""),
            _make_tool(git_diff_tool, _git_session),
            _make_tool(git_revert_hint_tool, _git_session),
            _make_tool(bootstrap_progress_tool, _harness_progress_tracker),
            _make_tool(save_progress_tool, _harness_progress_tracker),
            _make_tool(update_task_tool, _harness_progress_tracker),
            _make_tool(get_next_task_tool, _harness_progress_tracker),
            _make_tool(add_task_tool, _harness_progress_tracker),
            _make_tool(create_initializer_tool, resolved_llm, resolved_store, agent_name, harness_project_name),
        ]
        resolved_tools = resolved_tools + harness_tools
        logger.info(f"{agent_name}: Harness enabled — {len(harness_tools)} tools injected (progress + git)")

    elif harness and resolved_store is None:
        logger.warning(f"{agent_name}: harness=True requires store= to be provided. Harness disabled.")

    config: dict = {
        "name": agent_name,
        "llm": resolved_llm,
        "tools": resolved_tools,
        "system_prompt": resolved_prompt,
        "user_id": user_id or "default_user",
        "memory": resolved_memory,
        "store": resolved_store,
        "query_cache": resolved_query_cache,
        "registry": dict(_HANDLERS),
        "max_concurrent": max_concurrent,
        "max_retries": max_retries,
        "retry_delay": retry_delay,
        "llm_timeout": llm_timeout,
        "classifier_timeout": classifier_timeout,
        "structured_max_retries": structured_max_retries,
        "rate_limit": rate_limit,
        "low_score_threshold": low_score_threshold,
        "review_every_n_runs": review_every_n_runs,
        "trend_every_n_runs": trend_every_n_runs,
        "max_skills": max_skills,
        "max_reflection_iterations": max_reflection_iterations,
        "reflection_threshold": reflection_threshold,
        "interrupt_before": list(interrupt_before or []),
        "interrupt_after": list(interrupt_after or []),
        "interrupt_before_tools": list(ibi_merged),
        "interrupt_before_workers": list(interrupt_before_workers or []),
        "interrupt_after_workers": list(interrupt_after_workers or []),
        "user_callback": user_callback,
        "checkpointer": checkpointer,
        "middleware": list(middleware),
        "response_format": response_format,
        "debug": debug,
        "compiled_graph": None,
        "signal_queue": asyncio.Queue(),
        "clarification_queues": {},
        "_feedback": {},
        "_harness_enabled": _harness_enabled,
        "_harness_project": harness_project_name,
        "_progress_tracker": _harness_progress_tracker,
        "_progress_tracker_factory": _progress_tracker_factory,
        "_git_session": _git_session,
        "frozen": frozen,
        "frozen_template": frozen_template or "",
        "input_key": input_key,
        "frozen_analysis": None,
        "_frozen_handler": None,
        "_frozen_lock": asyncio.Lock(),
        "frozen_analysis_ttl": frozen_analysis_ttl,
        "_frozen_analysis_ts": 0,
        "max_step_output_length": max_step_output_length,
        "fallback_pattern": fallback_pattern,
        "react_force_tool_choice_on_user_turn": react_force_tool_choice_on_user_turn,
        "react_tool_use_failed_auto_retries_hitl": react_tool_use_failed_auto_retries_hitl,
        "react_tool_use_failed_user_rounds": react_tool_use_failed_user_rounds,
        "_handoff_targets": [],
        "_delegate_targets": [],
        "_bg_delegation_manager": BackgroundDelegationManager(),
        "_cli_tools": cli_tools_kw,
        "_hitl_tool_allowlist": set(),
        "max_pattern_depth": max_pattern_depth,
        "max_orchestration_llm_calls": max_orchestration_llm_calls,
        "max_orchestration_tokens": max_orchestration_tokens,
        "enable_auto_escalation": enable_auto_escalation,
        "orchestration_plan_from_classifier": orchestration_plan_from_classifier,
        "escalation_rules": list(escalation_rules or ["default"]),
        "enable_pattern_spawns": enable_pattern_spawns,
        "enable_orchestration_llm_eval": enable_orchestration_llm_eval,
        "enable_dynamic_dag_nodes": enable_dynamic_dag_nodes,
        "enable_supervisor_worker_dispatch": enable_supervisor_worker_dispatch,
        "orchestration_evaluation_llm": orchestration_evaluation_llm,
    }

    if delegates:
        for d in delegates:
            if isinstance(d, HandoffTarget):
                config["_delegate_targets"].append(d)
            else:
                config["_delegate_targets"].append(
                    HandoffTarget(
                        d,
                        description=f"Delegate agent '{getattr(d, 'name', 'delegate')}' — "
                        f"tools: {[t.name for t in getattr(d, 'config', {}).get('tools', [])]}",
                    )
                )
        logger.event(
            f"{agent_name}: {len(config['_delegate_targets'])} delegate(s) registered: "
            f"{[t.name for t in config['_delegate_targets']]}"
        )

    config["_mcp_servers"] = list(mcp_servers or [])
    config["_mcp_client"] = None
    config["_mcp_connected"] = False
    config["_mcp_session_attempted"] = False
    config["_mcp_lock"] = asyncio.Lock()
    config["mcp_prompts"] = {}
    config["mcp_uris"] = {}

    config["skill_registry"] = None
    config["skill_injector"] = None
    config["skill_learner"] = None
    config["skill_generator"] = None
    config["skill_lifecycle"] = None
    config["_skills_bootstrapped"] = False
    config["_skills_lock"] = asyncio.Lock()

    if resolved_store is not None:
        from .skills.generator import SkillGenerator
        from .skills.injector import SkillInjector
        from .skills.learner import SkillLearner
        from .skills.lifecycle import SkillLifecycleManager
        from .skills.loader import make_load_skill_tool
        from .skills.registry import SkillRegistry

        skill_registry = SkillRegistry(
            resolved_store,
            agent_name,
            disk_mirror=skills_mirror_path,
        )
        skill_injector = SkillInjector(skill_registry)
        skill_learner = SkillLearner(
            resolved_llm,
            skill_registry,
            llm_timeout=llm_timeout,
            structured_max_retries=structured_max_retries,
        )
        skill_generator = SkillGenerator(
            resolved_llm,
            llm_timeout=llm_timeout,
            structured_max_retries=structured_max_retries,
        )
        skill_lifecycle = SkillLifecycleManager(
            llm=resolved_llm,
            store=resolved_store,
            registry=skill_registry,
            agent_name=agent_name,
            llm_timeout=llm_timeout,
            structured_max_retries=structured_max_retries,
            review_every_n_runs=review_every_n_runs,
            max_skills=max_skills,
        )

        load_tool = make_load_skill_tool(skill_registry)
        resolved_tools.append(load_tool)
        config["tools"] = resolved_tools

        config["skill_registry"] = skill_registry
        config["skill_injector"] = skill_injector
        config["skill_learner"] = skill_learner
        config["skill_generator"] = skill_generator
        config["skill_lifecycle"] = skill_lifecycle

    if resolved_store is not None and _FEEDBACK_AVAILABLE:
        try:
            config["_feedback"] = build_feedback_system(
                llm=resolved_llm,
                long_term_store=resolved_store,
                agent_name=agent_name,
                feedback_handler=feedback_handler,
                skill_lifecycle=config.get("skill_lifecycle"),
                trend_every_n=trend_every_n_runs,
                llm_timeout=llm_timeout,
                structured_max_retries=structured_max_retries,
                low_score_threshold=low_score_threshold,
            )
            logger.debug(
                f"{agent_name}: Feedback system initialised "
                f"(handler={type(feedback_handler).__name__ if feedback_handler else 'NoOp'})."
            )
        except Exception as exc:
            logger.warning(f"{agent_name}: build_feedback_system failed ({exc!r}) — feedback disabled for this agent.")
            config["_feedback"] = {}
    elif feedback_handler is not None:
        logger.warning(
            f"{agent_name}: feedback_handler was provided but store= is None. "
            f"FeedbackStore requires a long-term store — feedback disabled."
        )

    logger.event(
        f"create_agent: name={agent_name!r} "
        f"model={type(resolved_llm).__name__} "
        f"tools={[t.name for t in resolved_tools]} "
        f"memory={'yes' if resolved_memory else 'no'} "
        f"store={'yes' if resolved_store else 'no'} "
        f"cache={'yes' if resolved_query_cache else 'no'} "
        f"feedback={'yes' if config['_feedback'] else 'no'}"
    )

    ua = UnifiedAgent(config)
    if _task_agent_cell is not None:
        _task_agent_cell[0] = ua
    return ua


def create_agent_sync(
    *args: Any,
    **kwargs: Any,
) -> UnifiedAgent:
    """Synchronous wrapper for ``create_agent``.

    Uses ``asyncio.run`` when no loop is running; when a loop is already active (Jupyter,
    IPython, embedded async servers), runs ``create_agent`` in a dedicated thread with its own
    loop via :func:`_run_coroutine_in_new_loop`. Prefer ``await create_agent(...)`` in async code.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(create_agent(*args, **kwargs))

    future = _sync_bridge_executor().submit(_run_coroutine_in_new_loop, create_agent(*args, **kwargs))
    return future.result()
