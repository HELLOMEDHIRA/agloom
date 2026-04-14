# unified_agent.py
# ─────────────────────────────────────────────────────────────────────────────
# UnifiedAgent — Manager in the Manager–Worker architecture.
#
# Design decisions:
#
# 1. config dict IS the agent dict.
#    Pattern handlers receive it directly. They read what they need
#    (llm, tools, name, max_concurrent, etc.) and ignore the rest.
#    One dict — zero translation layers.
#
# 2. run_fresh() is a standalone function, not a method.
#    UnifiedAgent.ainvoke() assembles a per-run config spread and calls
#    run_fresh(). Keeps run_fresh() independently testable.
#
# 3. Memory is injected into the QUERY (augmented_query), not the
#    system_prompt. Each run is isolated — no cross-run bleed.
#
# 4. Never mutate self.config during a call.
#    ainvoke() creates a run_config spread with per-run signal_queue
#    and clarification_queues overrides. self.config is read-only.
#
# 5. No graph.py required for run_fresh.
#    _HANDLERS is defined locally below. graph.py (Stage 3) is used
#    only by get_state(), get_history(), and resume() — all lazy-imported.
#    Normal ainvoke() → run_fresh() → direct handler calls. No compiled
#    graph in the hot path.
#
# 6. Auto-resume via Command(resume=...) is NOT in ainvoke().
#
# 7. Frozen agents (frozen=True) — compile once, execute many.
#    create_agent(frozen=True, frozen_template="...", input_key="input")
#    First ainvoke() runs analyze_query() once and caches pattern + handler
#    behind an asyncio.Lock (concurrent-safe double-check pattern).
#    Every subsequent ainvoke() skips Steps 2.5, 3, 7 — no classify LLM call.
#    ainvoke() accepts str | dict. dict is only valid for frozen=True agents;
#    each key in input_key must be present or ValueError is raised immediately.
#    {input_key} placeholders are substituted in: frozen_template (→ query),
#    system_prompt, and analysis.subtasks[*].task — all via model_copy,
#    never by mutating the cached frozen_analysis.
#    The new direct-handler design does not use compiled.ainvoke() in
#    run_fresh(), so there is no graph state to resume from. L1 HITL is
#    handled by _check_pattern_interrupt() + user_callback. L2 by
#    per-worker InMemorySaver inside worker.py. resume() exists for
#    callers who explicitly invoke the compiled graph via get_state().
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Sequence
from functools import lru_cache
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import BaseTool, StructuredTool

from .classifier import analyze_query
from .delegation import (
    BackgroundDelegationManager,
    HandoffTarget,
    _build_delegation_context,
    make_agent_tool,
    resolve_handoff,
    run_delegate,
)
from .logging_utils import configure_package_logging, get_logger
from .mcp_support import MCPServerConfig
from .memory import (
    LongTermStore,
    SessionMemory,
    build_memory_context,
    create_memory_tools,
)
from .models import (
    DEFAULT_SYSTEM_PROMPT,
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
from .patterns.blackboard import handle_blackboard
from .patterns.hybrid_dag import handle_hybrid_dag
from .patterns.pipeline import handle_pipeline
from .patterns.planner_executor import handle_planner_executor
from .patterns.react import handle_react
from .patterns.reflection import handle_reflection
from .patterns.supervisor import handle_supervisor
from .patterns.swarm import handle_swarm

# ── Feedback system — optional, gracefully degraded when module absent ────────
try:
    from .feedback.wireup import (
        apply_user_feedback,
        build_feedback_system,
        run_fresh_feedback_hooks,
    )

    _FEEDBACK_AVAILABLE = True
except ImportError:
    _FEEDBACK_AVAILABLE = False

    async def build_feedback_system(*_, **__) -> dict:
        return {}

    async def run_fresh_feedback_hooks(*_, **__) -> None:
        pass

    async def apply_user_feedback(*_, **__) -> None:
        pass


logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Built-in DIRECT handler
# ─────────────────────────────────────────────────────────────────────────────


async def _handle_direct(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """Fallback for DIRECT when direct_response is missing — simple LLM call.

    When _event_queue is present (astream_events path), streams tokens
    in real-time via llm.astream() instead of waiting for llm.ainvoke().
    """
    steps: list[AgentStep] = (config or {}).get("_steps", [])
    usage: dict[str, int] = {}
    output = (analysis.direct_response or "").strip()
    event_queue = agent.get("_event_queue")
    ml = agent.get("max_step_output_length", 0)
    raw_messages: list = []

    if not output:
        _timeout = agent.get("llm_timeout", 120.0)
        messages = [
            SystemMessage(content=agent.get("system_prompt", "")),
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
                        content = content if isinstance(content, str) else str(content)
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
            output = response.content
            usage = _extract_token_usage(response)
            raw_messages = messages + [response]

        dur = round((time.perf_counter() - t0) * 1000, 1)
        step = _make_step(
            StepType.LLM_CALL,
            "direct_llm",
            input=query,
            output=output,
            duration_ms=dur,
            max_length=ml,
            **usage,
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


# ─────────────────────────────────────────────────────────────────────────────
#  Built-in Pattern Registry
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
#  Model / Tool / Prompt Helpers
# ─────────────────────────────────────────────────────────────────────────────


@lru_cache(maxsize=32)
def _init_chat_model(model_id: str) -> BaseChatModel:
    from langchain.chat_models import init_chat_model

    return init_chat_model(model_id, temperature=0)


def resolve_model(model: Any) -> BaseChatModel:
    """Accept a BaseChatModel instance or a model-id string. String IDs are LRU-cached (max 32)."""
    if isinstance(model, str):
        return _init_chat_model(model)
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


async def _emit_step_event(config: dict, step: AgentStep) -> None:
    """Push a live event to the event queue for a completed step.

    Called from run_fresh() and pattern handlers to provide real-time
    visibility into execution progress. No-op when _event_queue is absent
    (i.e. caller used ainvoke() rather than astream_events()).
    """
    queue = config.get("_event_queue")
    if queue is None:
        return
    event_type = _step_type_to_event_type(step.type)
    await queue.put(
        AgentEvent(
            type=event_type,
            data={
                "name": step.name,
                "input": step.input,
                "output": step.output,
                "duration_ms": step.duration_ms,
                **step.metadata,
            },
        )
    )


async def _emit_token_event(config: dict, content: str) -> None:
    """Push a single token chunk to the live event queue.

    Called during LLM streaming within astream_events() to provide
    real-time token-by-token output to the UI consumer.
    """
    queue = config.get("_event_queue")
    if queue is None:
        return
    await queue.put(AgentEvent(type="token", data={"content": content}))


RESERVED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "save_memory",
        "recall_memory",
        "load_skill",
    }
)

# Tracks (agent_name, store_id) pairs for duplicate-name detection.
# store_id=None means no shared store, so no namespace collision risk.
_active_agent_names: dict[tuple[str, int | None], int] = {}
_active_agent_names_lock = asyncio.Lock()


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
    """Track agent name and warn if a duplicate shares the same LongTermStore."""
    store_id = id(store) if store is not None else None
    key = (agent_name, store_id)
    _active_agent_names[key] = _active_agent_names.get(key, 0) + 1
    if _active_agent_names[key] > 1 and store_id is not None:
        logger.warning(
            f"[agloom] Multiple agents named '{agent_name}' share the same "
            f"LongTermStore (id={store_id}). They will share feedback records, "
            f"correction memory, learned skills, and LT memory namespaces. "
            f"If this is unintentional, use distinct names or separate stores."
        )


def _unregister_agent_name(agent_name: str, store: Any) -> None:
    """Remove an agent from the active name tracker (called on aclose)."""
    store_id = id(store) if store is not None else None
    key = (agent_name, store_id)
    count = _active_agent_names.get(key, 0)
    if count <= 1:
        _active_agent_names.pop(key, None)
    else:
        _active_agent_names[key] = count - 1


def normalize_tools(tools: Sequence[Any]) -> list[BaseTool]:
    """Normalise a mixed list (BaseTool, callable, dict) to BaseTool instances."""
    normalised: list[BaseTool] = []
    for t in tools:
        if isinstance(t, BaseTool):
            normalised.append(t)
        elif callable(t):
            normalised.append(StructuredTool.from_function(t))
        elif isinstance(t, dict):
            fn = t.get("function") or t.get("func")
            if fn:
                normalised.append(
                    StructuredTool.from_function(
                        func=fn,
                        name=t.get("name", fn.__name__),
                        description=t.get("description", ""),
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


# ─────────────────────────────────────────────────────────────────────────────
#  Async Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _maybe_await(value: Any) -> Any:
    """Transparently await coroutines; return sync values as-is."""
    if asyncio.iscoroutine(value):
        return await value
    return value


# ─────────────────────────────────────────────────────────────────────────────
#  Middleware Runners
# ─────────────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────────────
#  L1 Pattern-Level HITL
# ─────────────────────────────────────────────────────────────────────────────


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

    preview = f"\nOutput: {result.output[:100]}" if result else ""
    message = f"{config['name']} INTERRUPT-{phase.upper()} [{pattern}]\nQuery: {query[:100]}{preview}"
    logger.event(f"[HITL-L1] {message}")
    try:
        decision = await _maybe_await(callback("pattern_interrupt", message))
        return str(decision).strip().lower() not in ("no", "abort", "stop", "cancel")
    except Exception as exc:
        logger.error(f"[HITL-L1] user_callback raised {exc!r} — continuing (fail-open).")
        return True


# ─────────────────────────────────────────────────────────────────────────────
#  Response Format Post-Processing
# ─────────────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────────────
#  Session Turn Recording
# ─────────────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────────────
#  Checkpoint Persistence
# ─────────────────────────────────────────────────────────────────────────────


async def _save_checkpoint(
    checkpointer: Any,
    thread_id: str,
    result: ExecutionResult,
    query: str,
) -> None:
    """Write execution state to the user-provided checkpointer.

    Best-effort: failures are logged but never crash the run. Uses the
    LangGraph Checkpoint TypedDict format so get_tuple() / alist() work
    natively on the checkpointer without a compiled graph.
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
        channel_versions = dict.fromkeys(channel_values, 1)
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
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        if hasattr(checkpointer, "aput"):
            await checkpointer.aput(config, checkpoint, metadata, channel_versions)
        elif hasattr(checkpointer, "put"):
            checkpointer.put(config, checkpoint, metadata, channel_versions)
        logger.debug(f"Checkpoint saved: thread_id={thread_id} run_id={result.run_id}")
    except Exception as exc:
        logger.warning(f"_save_checkpoint failed ({exc!r}) — non-fatal.")


# ─────────────────────────────────────────────────────────────────────────────
#  Lazy MCP Connection
# ─────────────────────────────────────────────────────────────────────────────


async def _ensure_mcp_connected(config: dict) -> None:
    """Connect to MCP servers on first call; no-op after _mcp_connected is set."""
    if config.get("_mcp_connected") or not config.get("_mcp_servers"):
        return
    async with config["_mcp_lock"]:
        if config.get("_mcp_connected"):
            return
        from .mcp_support import connect_mcp_servers

        client = await connect_mcp_servers(
            servers=config["_mcp_servers"],
            agent=config,
            agent_name=config.get("name", "Agent"),
        )
        config["_mcp_client"] = client
        config["_mcp_connected"] = True


# ─────────────────────────────────────────────────────────────────────────────
#  Lazy Skill Bootstrap
# ─────────────────────────────────────────────────────────────────────────────


async def _ensure_skills_bootstrapped(config: dict) -> None:
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


# ─────────────────────────────────────────────────────────────────────────────
#  Frozen Agent Helpers
# ─────────────────────────────────────────────────────────────────────────────


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
        logger.event(f"[{name}] frozen agent — classifying template: {config['frozen_template'][:80]!r}")

        analysis: QueryAnalysis = await analyze_query(
            llm=config["llm"],
            query=config["frozen_template"],
            tools=config.get("tools", []),
            classifier_timeout=config.get("classifier_timeout", 30.0),
            structured_max_retries=config.get("structured_max_retries", 2),
            fallback_pattern=config.get("fallback_pattern"),
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
        for k, v in subs.items():
            result = result.replace(f"{{{k}}}", v)
        return result

    sub_query = _sub(frozen_template)
    sub_system_prompt = _sub(system_prompt)
    sub_analysis = analysis.model_copy(
        update={"subtasks": [st.model_copy(update={"task": _sub(st.task)}) for st in analysis.subtasks]}
    )
    return sub_query, sub_system_prompt, sub_analysis


# ─────────────────────────────────────────────────────────────────────────────
#  Delegation Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _extract_delegate_from_analysis(
    analysis: QueryAnalysis,
    targets: list[HandoffTarget],
) -> str | None:
    """
    Check if the classifier's reasoning mentions a registered delegate name.

    The classifier sees delegate descriptions via _build_delegation_context().
    If its reasoning references a delegate by [name], we extract and return
    that name for transparent hand-off routing.

    Returns the delegate name or None if no match.
    """
    if not targets:
        return None
    reasoning = (analysis.reasoning or "").lower()
    # Also check matched_skill — classifier may put the delegate name there
    matched = (getattr(analysis, "matched_skill", None) or "").lower()
    for t in targets:
        t_lower = t.name.lower()
        if t_lower in reasoning or t_lower in matched:
            return t.name
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  13-Step Pipeline
# ─────────────────────────────────────────────────────────────────────────────


async def run_fresh(
    config: dict,
    query: str | dict,
    effective_thread_id: str,
    effective_ltns: tuple,
    invoke_config: dict,
    context: dict,
    user_id: str | None = None,
) -> ExecutionResult:
    """
    13-step fresh execution pipeline. Called by UnifiedAgent.ainvoke()
    for every invocation (direct handler path — no compiled graph).

    Steps
    ─────
     1   before_agent middleware
     2   passive memory injection
     [frozen=True path: substitute {input_key} — skip 2.5, 3, 7]
     2.5 skill context injection        (dynamic path only)
     3   classify                       (dynamic path only)
     4   semantic cache check            cache_get after classify (pattern known)
     5   L1 interrupt_before gate
     6   DIRECT short-circuit
     7   select handler
     8   execute
     9   L1 interrupt_after gate
    10   after_agent middleware
    11   response_format
    11.5 skill learning + lifecycle
    11.6 feedback hooks                 non-blocking background task
    12   attach run_id + record turn + cache_set
    13   return

    run_id is generated at the very start so every early-return path carries
    the same UUID. Attached via model_copy() — never mutated on the object.

    Cache ordering (Step 4 after classify):
      cache_get uses the pattern as a TTL-bucket key — must classify first.
      Cost: 1 classify LLM call even on cache hit.

    Feedback hooks (Step 11.6):
      Never blocks the return path. UserFeedbackHandler fires only when
      agent.feedback() is called explicitly.
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

    # Frozen dict queries are substituted later; middleware and memory always
    # receive a plain string.
    raw_query_str: str = query if isinstance(query, str) else " ".join(str(v) for v in query.values())

    # ── before_agent middleware ───────────────────────────────────────────────
    processed_query = await _run_before_agent(config.get("middleware", []), raw_query_str, context)

    # ── Resolve callable system_prompt per-run ──────────────────────────────
    sp = config["system_prompt"]
    if callable(sp) and not isinstance(sp, str):
        _sp_state = {
            "messages": [],
            "query": raw_query_str,
            "context": context,
            "thread_id": effective_thread_id,
            "user_id": user_id,
        }
        resolved_sp = await _maybe_await(sp(_sp_state))
        if isinstance(resolved_sp, SystemMessage):
            resolved_sp = resolved_sp.content if isinstance(resolved_sp.content, str) else str(resolved_sp.content)
        config = {**config, "system_prompt": resolved_sp or DEFAULT_SYSTEM_PROMPT}

    # ── Passive memory injection ────────────────────────────────────────────
    memory_ctx = await build_memory_context(
        session=memory,
        store=store,
        thread_id=effective_thread_id,
        namespace=effective_ltns,
        query=processed_query,
    )

    # ── FROZEN vs DYNAMIC path split ──────────────────────────────────────────
    is_frozen = config.get("frozen") and config.get("frozen_analysis") is not None

    if is_frozen:
        sub_query, sub_system_prompt, analysis = _apply_frozen_substitution(
            query=query,
            frozen_template=config["frozen_template"],
            system_prompt=config["system_prompt"],
            analysis=config["frozen_analysis"],
            input_key=config.get("input_key", "input"),
        )
        # Per-run config spread — never mutates the original agent config.
        config = {**config, "system_prompt": sub_system_prompt}
        augmented_query = f"{memory_ctx}\n{sub_query}" if memory_ctx else sub_query
        handler = config["_frozen_handler"]
        pattern_val = analysis.pattern.value
        logger.event(
            f"[{name}] frozen path — pattern={pattern_val} (skipped skill injection, classify, handler lookup)"
        )
    else:
        # ── Skill context injection ──────────────────────────────────────────
        skill_ctx = ""
        skill_injector = config.get("skill_injector")
        if skill_injector:
            try:
                skill_ctx = await skill_injector.get_context(processed_query)
            except Exception as exc:
                logger.warning(f"[{name}] skill_injector failed ({exc!r}) — proceeding without.")

        # ── Delegation context injection ─────────────────────────────────────
        handoff_targets = config.get("_handoff_targets") or []
        delegate_targets = config.get("_delegate_targets") or []
        all_delegation_targets = handoff_targets + delegate_targets
        delegation_ctx = _build_delegation_context(all_delegation_targets)
        if delegation_ctx and skill_ctx:
            skill_ctx = f"{skill_ctx}\n\n{delegation_ctx}"
        elif delegation_ctx:
            skill_ctx = delegation_ctx

        # ── Classify ──────────────────────────────────────────────────────────
        augmented_query = f"{memory_ctx}\n{processed_query}" if memory_ctx else processed_query
        t_classify = time.perf_counter()
        analysis: QueryAnalysis = await analyze_query(
            llm=config["llm"],
            query=augmented_query,
            tools=config.get("tools", []),
            skill_context=skill_ctx,
            classifier_timeout=config.get("classifier_timeout", 30.0),
            structured_max_retries=config.get("structured_max_retries", 2),
            fallback_pattern=config.get("fallback_pattern"),
        )
        classify_ms = round((time.perf_counter() - t_classify) * 1000, 1)
        classify_step = _make_step(
            StepType.CLASSIFY,
            "analyze_query",
            input=augmented_query,
            output=f"pattern={analysis.pattern.value} complexity={analysis.complexity}",
            max_length=ml,
            duration_ms=classify_ms,
            subtasks=len(analysis.subtasks),
        )
        _steps.append(classify_step)
        await _emit_step_event(config, classify_step)
        logger.event(
            f"[{name}] classify → pattern={analysis.pattern.value} "
            f"complexity={analysis.complexity} "
            f"subtasks={len(analysis.subtasks)}"
        )
        logger.debug(f"[{name}] Analysis: {analysis.model_dump()}")
        pattern_val = analysis.pattern.value
        handler = None

        # ── Transparent handoff routing ──────────────────────────────────────
        # If delegates are registered, check whether the classifier's reasoning
        # mentions a delegate name → route transparently.
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

        # ── Semantic cache check ─────────────────────────────────────────────
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

    # ── L1 interrupt_before gate ────────────────────────────────────────────
    # Must come BEFORE the DIRECT short-circuit so interrupt_before=["DIRECT"]
    # is honoured.
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

    # ── DIRECT short-circuit (dynamic path only) ────────────────────────────
    # Frozen mode skips this: direct_response belongs to the template, not the
    # actual input. Custom handlers via register_pattern() must always run.
    _has_custom_direct = registry.get(PatternType.DIRECT) is not _handle_direct
    if not is_frozen and analysis.pattern == PatternType.DIRECT and analysis.direct_response and not _has_custom_direct:
        direct_step = _make_step(
            StepType.LLM_CALL,
            "direct_shortcircuit",
            input=raw_query_str,
            output=analysis.direct_response,
            max_length=ml,
        )
        _steps.append(direct_step)
        await _emit_step_event(config, direct_step)
        result = ExecutionResult(
            pattern_used=PatternType.DIRECT,
            query=raw_query_str,
            output=analysis.direct_response,
            steps_taken=1,
            success=True,
            analysis=analysis,
            run_id=run_id,
            steps=_steps,
        )

        # L1 interrupt_after — must fire even on DIRECT short-circuit path
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
                )

        result = await _run_after_agent(config.get("middleware", []), result, context)
        await _record_turn(memory, effective_thread_id, raw_query_str, result, user_id, effective_ltns)
        if cache:
            try:
                from .cache import cache_set

                await cache_set(cache, processed_query, pattern_val, result.output)
            except Exception as exc:
                logger.debug(f"[{name}] cache_set (DIRECT) failed: {exc!r}")

        _maybe_fire_feedback_hooks(config, result, raw_query_str, name, skill_used=analysis.matched_skill)

        logger.event(f"[{name}] DIRECT short-circuit — 1 LLM call total.")
        return result

    # ── Select handler (dynamic path only) ──────────────────────────────────
    if not is_frozen:
        handler = registry.get(analysis.pattern)
        if handler is None:
            logger.warning(f"[{name}] No handler for pattern '{pattern_val}' — falling back to REACT.")
            handler = handle_react

    # ── Execute ──────────────────────────────────────────────────────────────
    logger.event(f"[{name}] execute → {pattern_val}")
    assert handler is not None, "handler must be set by frozen or dynamic path"
    exec_invoke_config = {**(invoke_config or {}), "_steps": _steps}
    t_exec = time.perf_counter()
    result: ExecutionResult = await handler(config, augmented_query, analysis, exec_invoke_config)
    exec_ms = round((time.perf_counter() - t_exec) * 1000, 1)
    logger.debug(f"[{name}] pattern execution took {exec_ms}ms")

    # ── L1 interrupt_after gate ─────────────────────────────────────────────
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

    # ── after_agent middleware ──────────────────────────────────────────────
    result = await _run_after_agent(config.get("middleware", []), result, context)

    # ── Response format ───────────────────────────────────────────────────────
    result = await _apply_response_format(
        config["llm"],
        result,
        config.get("response_format"),
        llm_timeout=config.get("llm_timeout", 120.0),
        structured_max_retries=config.get("structured_max_retries", 2),
    )

    # ── Skill learning + lifecycle ──────────────────────────────────────────
    skill_learner = config.get("skill_learner")
    if skill_learner:
        try:
            skill_learner.maybe_learn(result, query, name)
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

    # On-demand skill generation: if no skill matched a complex query,
    # fire a background task to generate a skill template so the NEXT
    # similar query benefits. Never blocks the current run.
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
                skill = await skill_generator.generate_for_query(query=query, tools=tools_for_gen, agent_name=name)
                if skill and registry_for_gen:
                    await registry_for_gen.save_learned_skill(
                        name=skill.name,
                        description=skill.description,
                        body=skill.body,
                        scope="global",
                        tags=["on-demand", "auto-generated"],
                    )
            except Exception as exc:
                logger.debug(f"[{name}] on-demand skill save failed: {exc!r}")

        from .llm_utils import safe_create_task

        safe_create_task(_bg_gen(), name=f"skill-gen-{name[:8]}")

    # ── Feedback hooks (non-blocking) ───────────────────────────────────────
    _maybe_fire_feedback_hooks(config, result, raw_query_str, name, skill_used=analysis.matched_skill)

    # ── Aggregate token usage from workers ──────────────────────────────────
    for wr in result.worker_results:
        if hasattr(wr, "token_usage") and wr.token_usage:
            _total_usage = _merge_token_usage(_total_usage, wr.token_usage)
    if result.token_usage:
        _total_usage = _merge_token_usage(_total_usage, result.token_usage)

    # Merge steps from the result (populated by the handler) with our own
    all_steps = _steps + [s for s in result.steps if s not in _steps]

    # ── Attach run_id + record turn + cache_set ────────────────────────────
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

    # ── Return ───────────────────────────────────────────────────────────────
    logger.event(
        f"[{name}] done — run_id={run_id} frozen={is_frozen} success={result.success} output={len(result.output)} chars"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
#  Feedback Hook Helper
# ─────────────────────────────────────────────────────────────────────────────


def _maybe_fire_feedback_hooks(
    config: dict,
    result: ExecutionResult,
    query: str,
    name: str,
    skill_used: str | None = None,
) -> None:
    """Fire feedback hooks if configured. Failures are swallowed."""
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


# ─────────────────────────────────────────────────────────────────────────────
#  UnifiedAgent Class
# ─────────────────────────────────────────────────────────────────────────────


class UnifiedAgent:
    """
    Manager agent — drop-in replacement for LangChain's create_agent() return value.

    Mirrors the Runnable interface (ainvoke / astream / invoke).
    Adds: get_state(), get_history(), register_pattern(), resume(), feedback().

    Execution model (Design Decision #5)
    ────────────────────────────────────
    Normal ainvoke() → run_fresh() → direct handler calls. No compiled
    graph in the hot path. This makes run_fresh() independently testable
    and removes graph compilation overhead per call.

    The compiled graph is lazily built only when needed for:
      get_state()    — LangGraph state inspection
      get_history()  — time-travel over state snapshots
      resume()       — Command(resume=...) for graph-based HITL

    Concurrency
    ───────────
    Each ainvoke() call creates a fresh signal_queue and clarification_queues
    injected into invoke_config["configurable"]. Two simultaneous ainvoke()
    calls are fully isolated — they cannot cross-post signals or answers.

    Memory
    ──────
    config["memory"] → SessionMemory (always active)
    config["store"]  → LongTermStore (optional, cross-session recall)
    Both are set at create_agent() time — never replaced during a call.

    Feedback
    ────────
    config["_feedback"] → feedback system config dict (from build_feedback_system())
    agent.feedback(run_id, rating, correct=...) → routes to FeedbackStore +
    UserFeedbackHandler. run_id is surfaced on every ExecutionResult.
    """

    def __init__(self, config: dict) -> None:
        self.config = config

    # ── Async context manager for graceful shutdown ───────────────────────────

    async def __aenter__(self) -> UnifiedAgent:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Release all held resources: MCP connections, thread pools, HTTP clients."""
        if self.config.get("_mcp_client") is not None:
            try:
                client = self.config["_mcp_client"]
                if hasattr(client, "__aexit__"):
                    await client.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug(f"[{self.name}] MCP client cleanup: {exc!r}")
            self.config["_mcp_client"] = None
            self.config["_mcp_connected"] = False

        fb = self.config.get("_feedback", {})
        handler = fb.get("handler")
        if handler is not None and hasattr(handler, "aclose"):
            try:
                await handler.aclose()
            except Exception as exc:
                logger.debug(f"[{self.name}] Feedback handler cleanup: {exc!r}")

        _unregister_agent_name(self.name, self.config.get("store"))
        logger.debug(f"[{self.name}] aclose() complete — resources released")

    @property
    def name(self) -> str:
        return self.config["name"]

    # ── ID Resolution ─────────────────────────────────────────────────────────

    def resolve_ids(
        self,
        thread_id: str | None,
        user_id: str | None,
        lt_namespace: tuple | None,
    ) -> tuple[str, tuple, dict]:
        """
        Resolve effective identifiers for this invocation.

        Returns: (effective_thread_id, effective_ltns, invoke_config)

        Namespace priority:
          1. lt_namespace — explicit override (multi-agent shared state)
          2. user_id      — stable cross-session namespace → (name, user_id)
          3. thread_id    — ephemeral fallback             → (name, thread_id)

        invoke_config["configurable"] carries:
          thread_id            → LangGraph state scoping (checkpointer)
          memory_namespace     → memory tools store resolution
          signal_queue         → per-run HALT_ALL / CLARIFICATION isolation
          clarification_queues → per-worker answer routing dict (CLARIFICATION_REQUEST)
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
                "signal_queue": asyncio.Queue(),  # fresh per-run
                "clarification_queues": {},  # populated by clarification_tool.py
            }
        }
        return effective_thread_id, effective_ltns, invoke_config

    # ── Public API ────────────────────────────────────────────────────────────

    async def ainvoke(
        self,
        query: str | dict,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
    ) -> ExecutionResult:
        """
        Primary async entry point.

        thread_id=None      ephemeral UUID — no cross-call memory
        thread_id="t1"      stateful session — session memory active
        user_id="u123"      stable cross-session LT namespace
        lt_namespace=(...)  explicit shared namespace (multi-agent)

        query accepts str | dict:
          str  — always valid (frozen and non-frozen agents)
          dict — only valid when frozen=True; keys must match input_key exactly.
                 Raises ValueError immediately if a key is missing.

        HITL in the direct-handler path:
          L1 — _check_pattern_interrupt() calls user_callback before/after pattern.
          L2 — per-worker InMemorySaver inside worker.py enables tool-level interrupt().
          L3 — hitl.py gates workers via interrupt_before/after_workers lists.
          L4 — signal_queue carries HALT_ALL and CLARIFICATION_REQUEST signals.

        The returned ExecutionResult carries a run_id UUID. Pass it to
        agent.feedback() to submit post-run corrections or ratings.
        """
        # ── Frozen contract enforcement ──────────────────────────────────────
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

        await _ensure_mcp_connected(self.config)
        await _ensure_skills_bootstrapped(self.config)

        if self.config.get("frozen"):
            await _ensure_frozen_analysis(self.config)

        # Per-run config spread — NEVER mutates self.config
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
            query if isinstance(query, str) else str(query),
        )

        return result

    async def astream(
        self,
        query: str | dict,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
        stream_mode: str = "tokens",
    ) -> AsyncGenerator[Any, None]:
        """
        Async streaming entry point.

        For DIRECT pattern: uses LLM's native astream() for real token streaming.
        For complex patterns: runs full ainvoke() then simulates word-by-word
        streaming (true token-level streaming for multi-step patterns is a future priority).

        stream_mode="tokens"  → yield str token/word chunks
        stream_mode="result"  → yield single ExecutionResult at end

        Usage:
            async for token in agent.astream("Research X", thread_id="t1"):
                print(token, end="", flush=True)
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

        words = result.output.split(" ")
        for i, word in enumerate(words):
            yield word + ("" if i == len(words) - 1 else " ")
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
        """
        Attempt true token streaming for DIRECT-eligible queries.
        Returns an async generator of string chunks, or None if the query
        is not DIRECT-eligible (caller should fall back to ainvoke).
        """
        try:
            await _ensure_mcp_connected(self.config)
            await _ensure_skills_bootstrapped(self.config)

            effective_thread_id, effective_ltns, _inv = self.resolve_ids(thread_id, user_id, lt_namespace)
            ctx = context or {}

            raw_query_str = query
            processed_query = await _run_before_agent(self.config.get("middleware", []), raw_query_str, ctx)

            sp = self.config["system_prompt"]
            resolved_sp = sp
            if callable(sp) and not isinstance(sp, str):
                _sp_state = {
                    "messages": [],
                    "query": raw_query_str,
                    "context": ctx,
                    "thread_id": effective_thread_id,
                    "user_id": user_id,
                }
                resolved_sp = await _maybe_await(sp(_sp_state))
                if isinstance(resolved_sp, SystemMessage):
                    resolved_sp = (
                        resolved_sp.content if isinstance(resolved_sp.content, str) else str(resolved_sp.content)
                    )
                resolved_sp = resolved_sp or DEFAULT_SYSTEM_PROMPT

            memory = self.config.get("memory")
            store = self.config.get("store")
            memory_ctx = await build_memory_context(
                session=memory,
                store=store,
                thread_id=effective_thread_id,
                namespace=effective_ltns,
                query=processed_query,
            )

            skill_ctx = ""
            skill_injector = self.config.get("skill_injector")
            if skill_injector:
                try:
                    skill_ctx = await skill_injector.get_context(processed_query)
                except Exception:
                    pass

            augmented_query = f"{memory_ctx}\n{processed_query}" if memory_ctx else processed_query
            analysis = await analyze_query(
                llm=self.config["llm"],
                query=augmented_query,
                tools=self.config.get("tools", []),
                skill_context=skill_ctx,
                classifier_timeout=self.config.get("classifier_timeout", 30.0),
                structured_max_retries=self.config.get("structured_max_retries", 2),
                fallback_pattern=self.config.get("fallback_pattern"),
            )

            if analysis.pattern != PatternType.DIRECT:
                return None

            if analysis.pattern.value in self.config.get("interrupt_before", []):
                return None

            async def _stream_direct() -> AsyncGenerator[str, None]:
                llm = self.config["llm"]
                messages = [SystemMessage(content=resolved_sp), HumanMessage(content=query)]
                async for chunk in llm.astream(messages):
                    content = chunk.content
                    if content:
                        yield content if isinstance(content, str) else str(content)

            return _stream_direct()
        except Exception as exc:
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
        """
        Run multiple queries concurrently through the same agent.

        Each query gets its own isolated signal_queue and thread_id (unless shared
        thread_id is passed). Concurrency is bounded by max_concurrent.

        Usage:
            results = await agent.abatch(["Query 1", "Query 2", "Query 3"])
        """
        sem = asyncio.Semaphore(max_concurrent)

        async def _run_one(q: str | dict) -> ExecutionResult:
            async with sem:
                return await self.ainvoke(
                    q,
                    thread_id=thread_id,
                    user_id=user_id,
                    lt_namespace=lt_namespace,
                    context=context,
                )

        return list(await asyncio.gather(*[_run_one(q) for q in queries]))

    async def astream_events(
        self,
        query: str | dict,
        *,
        thread_id: str | None = None,
        user_id: str | None = None,
        lt_namespace: tuple | None = None,
        context: dict | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """
        Live event streaming API for ChatGPT-style "thinking" UIs.

        Events are emitted in real-time as the pipeline executes — not
        replayed after completion. Token events stream during each LLM
        call, giving production chat UIs the typing effect users expect.

        Yields AgentEvent objects as the agent executes:
          type="thinking"      — classify/analysis step
          type="llm_call"      — LLM call completed (metadata/duration)
          type="tool_call"     — tool invocation (includes id for correlation)
          type="tool_result"   — tool response (includes matching id)
          type="worker_start"  — worker begins
          type="worker_end"    — worker completes
          type="token"         — real-time streaming token chunk
          type="done"          — final result with full ExecutionResult

        Token streaming works for ALL patterns — DIRECT, REACT, SUPERVISOR,
        etc. Each LLM call in the pipeline streams tokens as they arrive.

        Combined token + event mode: this single API provides BOTH
        structured step events AND real-time token chunks, matching the
        industry standard set by LangGraph's astream_events(version="v2").

        Usage:
            async for event in agent.astream_events("Explain X",
                                                     thread_id="t1",
                                                     user_id="u123"):
                if event.type == "thinking":
                    print(f"Analyzing: {event.data.get('output', '')}")
                elif event.type == "token":
                    print(event.data["content"], end="", flush=True)
                elif event.type == "tool_call":
                    tc_id = event.data.get("id", "")
                    print(f"\\nCalling {event.data['name']} [{tc_id}]...")
                elif event.type == "tool_result":
                    tc_id = event.data.get("id", "")
                    print(f"Result [{tc_id}]: {event.data['output'][:50]}")
                elif event.type == "done":
                    final_result = event.data["result"]
        """
        event_queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def _run_and_push() -> None:
            try:
                effective_thread_id, effective_ltns, invoke_config = self.resolve_ids(thread_id, user_id, lt_namespace)

                await _ensure_mcp_connected(self.config)
                await _ensure_skills_bootstrapped(self.config)

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
                    query if isinstance(query, str) else str(query),
                )

                await event_queue.put(
                    AgentEvent(
                        type="done",
                        data={"result": result.model_dump()},
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

        while True:
            event = await event_queue.get()
            if event is None:
                break
            yield event

        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None:
                raise exc

    def invoke(
        self,
        query: str | dict,
        **kwargs,
    ) -> ExecutionResult:
        """
        Synchronous wrapper around ainvoke().

        Handles three scenarios:
          1. No running loop → asyncio.run() (cleanest)
          2. Running loop exists (Jupyter, nested frameworks) → thread offload
          3. Fallback → new loop in current thread
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None:
            return asyncio.run(self.ainvoke(query, **kwargs))

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, self.ainvoke(query, **kwargs))
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
        """
        Submit user feedback for a completed run.

        Routing:
          1. FeedbackStore.record()        — persists rating + correction
          2. UserFeedbackHandler.handle()  — triggers configured action
             (NoOp / LTS memory + skill decay / Webhook / Composite)

        run_id comes from result.run_id returned by ainvoke().

        Example:
            result = await agent.ainvoke("Explain RLHF")
            await agent.feedback(
                result.run_id,
                "negative",
                correct="RLHF = Reinforcement Learning from Human Feedback",
            )
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
        """
        Resume a paused COMPILED graph via LangGraph Command(resume=value).

        This method applies only to callers using the compiled graph path
        (e.g. via get_state() / get_history()). Normal ainvoke() runs through
        run_fresh() and does not produce compilable graph state.

        Requires checkpointer — pass checkpointer=InMemorySaver() to create_agent().
        """
        from langgraph.types import Command

        compiled = self.config.get("compiled_graph")
        if compiled is None:
            try:
                from .graph import build_agent_graph

                compiled = build_agent_graph(self.config)
                self.config["compiled_graph"] = compiled
            except ImportError:
                return ExecutionResult(
                    pattern_used=PatternType.REACT,
                    query=str(value),
                    output=(
                        "Resume requires a compiled graph with checkpointer. "
                        "Pass checkpointer=InMemorySaver() to create_agent()."
                    ),
                    steps_taken=1,
                    success=False,
                )

        memory = self.config.get("memory")
        logger.event(f"[{self.name}] resume: thread={thread_id} value={str(value)[:60]}")
        try:
            cfg = invoke_config or {"configurable": {"thread_id": thread_id}}
            state = await compiled.ainvoke(  # type: ignore[no-matching-overload]
                Command(resume=value),
                config=cfg,
            )
            result = state.get("result")
            if result:
                await _record_turn(
                    memory,
                    thread_id,
                    f"RESUME: {str(value)[:200]}",
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
        """
        Current state snapshot for a thread.

        Returns the latest checkpoint written by ainvoke()/astream_events()
        via the checkpointer. If no checkpoint exists for this thread,
        returns None.

        Requires checkpointer — pass checkpointer=MemorySaver() to create_agent().
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
        """
        Async iterator over full state history for a thread (time-travel).

        Each item is a CheckpointTuple containing the checkpoint data
        written by ainvoke()/astream_events(). Requires checkpointer.
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
        """
        Register or override a pattern handler at runtime.
        Takes effect immediately on the next ainvoke() call.
        """
        self.config["registry"][pattern_type] = handler_fn
        logger.event(f"[{self.name}] Pattern registered: {pattern_type.value}")

    # ── Delegation API ───────────────────────────────────────────────────────

    def as_tool(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> BaseTool:
        """
        Wrap this agent as a LangChain tool for use in another agent's tool list.

        Usage:
            research = create_agent(model=llm, name="researcher", ...)
            parent = create_agent(model=llm, tools=[research.as_tool()])
        """
        return make_agent_tool(self, name=name, description=description)

    def register_handoff(
        self,
        target: Any,  # HandoffTarget | UnifiedAgent
        *,
        name: str | None = None,
        description: str = "",
        filter_fn: Callable | None = None,
        input_transform: Callable | None = None,
    ) -> None:
        """
        Register a transparent hand-off target.

        When registered, the classifier sees the delegate's description and
        can route queries directly to it. The hand-off is transparent — the
        caller receives the delegate's result as if the parent handled it.

        Accepts either a HandoffTarget or a raw UnifiedAgent (which gets
        wrapped automatically).

        Usage:
            parent.register_handoff(
                research_agent,
                description="Research and summarize academic papers",
            )
        """
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
        """
        Explicitly delegate a query to a registered delegate.

        If delegate_name is given, routes to that specific delegate.
        Otherwise, resolves the best match from handoff targets and
        the delegates list.

        Raises ValueError if no matching delegate is found.
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
        """
        Fire-and-forget background delegation. Returns task_id immediately.

        Usage:
            task_id = await parent.adelegate_background(
                "Research quantum computing",
                delegate_name="researcher",
            )
            # Later:
            result = await parent.await_background(task_id)
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
        """Wait for a background delegation to complete. Returns the result or None."""
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


# ─────────────────────────────────────────────────────────────────────────────
#  Factory
# ─────────────────────────────────────────────────────────────────────────────


def create_agent(
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
    classifier_timeout: float = 30.0,
    structured_max_retries: int = 2,
    rate_limit: float | None = None,
    low_score_threshold: float = 0.40,
    review_every_n_runs: int = 25,
    trend_every_n_runs: int = 100,
    max_skills: int = 30,
    session_max_turns: int = 20,
    max_reflection_iterations: int = 3,
    reflection_threshold: int = 7,
    mcp_servers: list[MCPServerConfig] | None = None,
    max_step_output_length: int = 0,
    fallback_pattern: PatternType | None = None,
    auto_summarize: bool = True,
    summarize_threshold: int = 200_000,
    summarizer_model: Any = None,
    # ── Feedback system ──────────────────────────────────────────────────────
    # feedback_handler: plug-and-play UserFeedbackHandler implementation.
    # Accepted values (all from feedback/user_feedback.py):
    #   None                   → NoOpFeedbackHandler (default — zero overhead)
    #   LTSFeedbackHandler     → saves rating, signals skill decay, stores corrections
    #   WebhookFeedbackHandler → POSTs payload to a URL
    #   CompositeHandler       → chains multiple handlers concurrently
    #   Any custom class implementing UserFeedbackHandler protocol
    # Only active when store= is also provided (FeedbackStore is LTS-backed).
    feedback_handler: Any | None = None,
    # ── Delegation ────────────────────────────────────────────────────────────
    # delegates: list of (UnifiedAgent | HandoffTarget) that this agent can
    # dispatch work to via run_delegate(). Exposed to the classifier so it
    # can route transparently. Also accessible via agent.adelegate().
    delegates: Sequence[Any] | None = None,
    # ── Frozen agent ─────────────────────────────────────────────────────────
    # frozen=True  → classify once on first ainvoke(), reuse forever.
    #                ainvoke() accepts str | dict. dict requires input_key list.
    # frozen=False → full 13-step classify pipeline on every call (default).
    frozen: bool = False,
    frozen_template: str | None = None,  # required when frozen=True
    input_key: str | list[str] = "input",  # {placeholder} name(s)
    frozen_analysis_ttl: float = 0,  # seconds; 0 = never expire
) -> UnifiedAgent:
    """
    Factory that validates all inputs and returns a fully wired UnifiedAgent.

    Validation:
      AgentConfig (Pydantic model) validates all inputs at construction time.
      It is discarded after validation — the internal pipeline is dict-based.

    Frozen mode (frozen=True):
      Analysis runs once on first ainvoke() — pattern + handler cached forever.
      Every subsequent call skips Steps 2.5, 3, 7 — saving one LLM classify
      call (~200-500 ms) per invocation. Ideal for batch workloads where
      system_prompt and structure are fixed; only the input data changes.
      Requires frozen_template with {input_key} placeholder(s).

    Feedback:
      When store= is provided, build_feedback_system() is called automatically.
      AutoEvaluator runs after every run_fresh() call (mandatory).
      UserFeedbackHandler is activated by calling agent.feedback() explicitly.
      When store= is None, the feedback system is silently disabled.

    Skill system:
      Activated automatically when store= is provided. First ainvoke() call
      bootstraps skills from disk and runs lifecycle hygiene (lazy init).
    """
    # ── Logging configuration (must precede everything else) ───────────────────
    configure_package_logging(debug)

    # ── Input validation (Pydantic) ────────────────────────────────────────────
    from .models import AgentConfig

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
        query_cache=query_cache,
        interrupt_before=interrupt_before or [],
        interrupt_after=interrupt_after or [],
        interrupt_before_tools=interrupt_before_tools or [],
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
        auto_summarize=auto_summarize,
        summarize_threshold=summarize_threshold,
        summarizer_model=summarizer_model,
    )

    # ── Frozen params validation ─────────────────────────────────────────────
    _validate_frozen_params(frozen, frozen_template, input_key)

    # ── Resolve and normalize inputs ──────────────────────────────────────────
    resolved_llm = resolve_model(model)
    resolved_prompt = resolve_system_prompt(system_prompt)
    agent_name = (name or "UnifiedAgent").strip()
    resolved_tools = normalize_tools(tools or [])
    _check_reserved_tool_names(resolved_tools)

    # ── Long-term store ───────────────────────────────────────────────────────
    resolved_store: LongTermStore | None = None
    if store is not None:
        resolved_store = store if isinstance(store, LongTermStore) else LongTermStore(store=store)

    # ── Duplicate name detection ──────────────────────────────────────────────
    _register_agent_name(agent_name, resolved_store)

    # ── Auto-inject memory tools ──────────────────────────────────────────────
    if resolved_store is not None and enable_memory_tools:
        mem_tools = create_memory_tools(resolved_store)
        resolved_tools = mem_tools + resolved_tools  # memory tools first

    # ── Session memory (always active) ────────────────────────────────────────
    resolved_summarizer = resolve_model(summarizer_model) if summarizer_model else resolved_llm
    resolved_memory = memory
    if resolved_memory is None:
        try:
            from langgraph.store.memory import InMemoryStore as LGStore

            resolved_memory = SessionMemory(
                store=LGStore(),
                max_turns=session_max_turns,
                auto_summarize=auto_summarize,
                summarize_threshold=summarize_threshold,
                summarizer_model=resolved_summarizer if auto_summarize else None,
            )
        except ImportError:
            resolved_memory = SessionMemory(
                max_turns=session_max_turns,
                auto_summarize=auto_summarize,
                summarize_threshold=summarize_threshold,
                summarizer_model=resolved_summarizer if auto_summarize else None,
            )
        logger.debug(
            f"{agent_name}: SessionMemory auto-created with ephemeral InMemoryStore. "
            f"auto_summarize={auto_summarize} threshold={summarize_threshold} "
            f"For persistence: memory=SessionMemory(store=AsyncSqliteStore(...))"
        )
    elif auto_summarize and resolved_memory.summarizer_model is None:
        resolved_memory.summarizer_model = resolved_summarizer

    # ── Core config dict ──────────────────────────────────────────────────────
    config: dict = {
        # Core
        "name": agent_name,
        "llm": resolved_llm,
        "tools": resolved_tools,
        "system_prompt": resolved_prompt,
        "user_id": user_id or "default_user",
        # Memory
        "memory": resolved_memory,
        "store": resolved_store,
        # Cache
        "query_cache": query_cache,
        # Pattern registry — per-instance copy so register_pattern() is isolated
        "registry": dict(_HANDLERS),
        # Execution tuning
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
        # HITL — L1 (pattern-level)
        "interrupt_before": list(interrupt_before or []),
        "interrupt_after": list(interrupt_after or []),
        # HITL — L2 (tool-level)
        "interrupt_before_tools": list(interrupt_before_tools or []),
        # HITL — L3 (worker-level)
        "interrupt_before_workers": list(interrupt_before_workers or []),
        "interrupt_after_workers": list(interrupt_after_workers or []),
        # HITL — shared callback
        "user_callback": user_callback,
        "checkpointer": checkpointer,
        # Advanced
        "middleware": list(middleware),
        "response_format": response_format,
        "debug": debug,
        # Lazily populated on first get_state() / get_history() / resume()
        "compiled_graph": None,
        # Agent-level fallback signal_queue — REPLACED per-call in ainvoke().
        # NEVER read this from run_fresh(); always read from invoke_config["configurable"].
        "signal_queue": asyncio.Queue(),
        "clarification_queues": {},
        "_feedback": {},
        # ── Frozen agent — analysis cached on first ainvoke() ────────────────
        "frozen": frozen,
        "frozen_template": frozen_template or "",
        "input_key": input_key,
        "frozen_analysis": None,
        "_frozen_handler": None,
        "_frozen_lock": asyncio.Lock(),
        "frozen_analysis_ttl": frozen_analysis_ttl,
        "_frozen_analysis_ts": 0,
        # Step output truncation (0 = no truncation)
        "max_step_output_length": max_step_output_length,
        # Classifier fallback pattern override
        "fallback_pattern": fallback_pattern,
        # ── Delegation ──────────────────────────────────────────────────────
        "_handoff_targets": [],  # populated by register_handoff()
        "_delegate_targets": [],  # populated from delegates= param below
        "_bg_delegation_manager": BackgroundDelegationManager(),
    }

    # ── Delegates (hierarchical delegation) ─────────────────────────────────
    if delegates:
        for d in delegates:
            if isinstance(d, HandoffTarget):
                config["_delegate_targets"].append(d)
            else:
                # Assume it's a UnifiedAgent — wrap with auto-generated description
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

    # ── MCP ───────────────────────────────────────────────────────────────────
    config["_mcp_servers"] = list(mcp_servers or [])
    config["_mcp_client"] = None
    config["_mcp_connected"] = False
    config["_mcp_lock"] = asyncio.Lock()
    config["mcp_prompts"] = {}
    config["mcp_uris"] = {}

    # ── Skill system (active when long-term store is provided) ────────────────
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

        skill_registry = SkillRegistry(resolved_store, agent_name)
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

    # ── Feedback system (active when long-term store is provided) ─────────────
    # When store is None, _feedback stays empty and hooks are silently skipped.
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
        f"cache={'yes' if query_cache else 'no'} "
        f"feedback={'yes' if config['_feedback'] else 'no'}"
    )

    return UnifiedAgent(config)
