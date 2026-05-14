"""Agent runtime: pattern routing, ``run_fresh`` execution, and ``UnifiedAgent`` facade.

``create_agent`` / ``create_agent_sync`` validate configuration and return ``UnifiedAgent``.
The default execution path is direct handler calls inside ``run_fresh``; a compiled LangGraph
is only materialized for checkpoint APIs (``get_state``, ``get_history``, ``resume``).
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections import OrderedDict
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

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
from .hitl_contract import HITLEvent, call_user_callback
from .logging_utils import configure_package_logging, get_logger
from .multimodal import merge_context_into_user_turn, text_from_user_turn
from .mcp_support import MCPServerConfig, aclose_mcp_client
from .memory import (
    LongTermStore,
    SessionMemory,
    build_memory_context,
    create_memory_tools,
)
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
from .patterns.blackboard import handle_blackboard
from .patterns.hybrid_dag import handle_hybrid_dag
from .patterns.pipeline import handle_pipeline
from .patterns.planner_executor import handle_planner_executor
from .patterns.react import handle_react
from .patterns.reflection import handle_reflection
from .patterns.supervisor import handle_supervisor
from .patterns.swarm import handle_swarm

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
            input=text_from_user_turn(query) if isinstance(query, list) else query,
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


@lru_cache(maxsize=32)
def _init_chat_model(model_id: str) -> BaseChatModel:
    from langchain.chat_models import init_chat_model

    return init_chat_model(model_id, temperature=0)


def resolve_model(model: Any) -> BaseChatModel:
    """Accept a BaseChatModel instance or a model-id string. String IDs are LRU-cached (max 32).

    String ids are delegated to ``langchain.chat_models.init_chat_model``; install the matching
    ``langchain-*`` integration from https://docs.langchain.com/oss/python/integrations/chat
    for providers beyond the default stack (AWS Bedrock, xAI, Mistral, …).
    """
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
    """Emit one token chunk to ``_event_queue``."""
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

_active_agent_names: dict[tuple[str, int | None], int] = {}


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


def _structured_tool_from_callable(
    fn: Callable[..., Any],
    *,
    name: str | None = None,
    description: str = "",
) -> StructuredTool:
    """Wrap a sync or async callable so LangChain awaits coroutine tools correctly."""
    nm = name or getattr(fn, "__name__", "tool")
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


async def _save_checkpoint(
    checkpointer: Any,
    thread_id: str,
    result: ExecutionResult,
    query: str,
    *,
    event_queue: Any = None,
    label: str | None = None,
) -> None:
    """Best-effort checkpoint write for ``get_state`` / ``get_history``."""
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
        # Emit MCP server names to the event stream so the CLI can display them
        eq = config.get("_event_queue")
        if eq is not None:
            names = [getattr(s, "name", str(s)) for s in config.get("_mcp_servers", [])]
            await eq.put(AgentEvent(type="runtime.mcp.servers", data={"server_names": names}))


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

        analysis: QueryAnalysis = await analyze_query(
            llm=config["llm"],
            query=config["frozen_template"],
            tools=config.get("tools", []),
            classifier_timeout=config.get("classifier_timeout", 60.0),
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


def _extract_delegate_from_analysis(
    analysis: QueryAnalysis,
    targets: list[HandoffTarget],
) -> str | None:
    """Return a delegate name if the classifier reasoning matches a registered target."""
    if not targets:
        return None
    reasoning = (analysis.reasoning or "").lower()
    matched = (getattr(analysis, "matched_skill", None) or "").lower()
    for t in targets:
        t_lower = t.name.lower()
        if t_lower in reasoning or t_lower in matched:
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

    if isinstance(query, str):
        raw_query_str = query
    elif isinstance(query, list):
        raw_query_str = text_from_user_turn(query)
    else:
        raw_query_str = " ".join(str(v) for v in query.values())

    processed_query = await _run_before_agent(config.get("middleware", []), raw_query_str, context)

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

    is_frozen = config.get("frozen") and config.get("frozen_analysis") is not None

    harness_ctx = ""
    if config.get("_harness_enabled") and not is_frozen:
        progress_tracker: ProgressTracker | None = config.get("_progress_tracker")
        if progress_tracker:
            try:
                harness_ctx = progress_tracker.get_classifier_context()
                logger.event(
                    f"[{name}] harness bootstrap: "
                    f"{len(progress_tracker.artifact.tasks)} tasks, "
                    f"progress={progress_tracker.artifact.completion_ratio:.0%}"
                )
            except Exception as exc:
                logger.warning(f"[{name}] harness bootstrap failed ({exc!r}) — proceeding")

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
        skill_ctx = ""
        skill_injector = config.get("skill_injector")
        if skill_injector:
            try:
                skill_ctx = await skill_injector.get_context(processed_query)
            except Exception as exc:
                logger.warning(f"[{name}] skill_injector failed ({exc!r}) — proceeding without.")

        handoff_targets = config.get("_handoff_targets") or []
        delegate_targets = config.get("_delegate_targets") or []
        all_delegation_targets = handoff_targets + delegate_targets
        delegation_ctx = _build_delegation_context(all_delegation_targets)
        if delegation_ctx and skill_ctx:
            skill_ctx = f"{skill_ctx}\n\n{delegation_ctx}"
        elif delegation_ctx:
            skill_ctx = delegation_ctx

        harness_block = f"\n\n=== CROSS-SESSION PROGRESS ===\n{harness_ctx}\n" if harness_ctx else ""
        augmented_query = (
            f"{memory_ctx}{harness_block}\n{processed_query}"
            if memory_ctx
            else (f"{harness_block}\n{processed_query}" if harness_ctx else processed_query)
        )
        eq = config.get("_event_queue")
        if skill_ctx.strip() and eq is not None:
            await eq.put(
                AgentEvent(
                    type="skill_context",
                    data={"phase": "classifier", "injected_chars": len(skill_ctx)},
                )
            )
        if eq is not None:
            await eq.put(
                AgentEvent(
                    type="thinking",
                    data={
                        "name": "analyze_query",
                        "input": augmented_query,
                        "output": "Running classifier…",
                    },
                )
            )
        t_classify = time.perf_counter()
        await _emit_graph_node_event(config, "graph_node_enter", node="classify", input_preview=augmented_query)
        analysis: QueryAnalysis = await analyze_query(
            llm=config["llm"],
            query=augmented_query,
            tools=config.get("tools", []),
            skill_context=skill_ctx,
            classifier_timeout=config.get("classifier_timeout", 60.0),
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
        sub_lines = [f"- {st.worker_id}: {st.task}" for st in analysis.subtasks]
        sub_block = "\n".join(sub_lines) if sub_lines else "(none)"
        classify_summary = (
            f"pattern={analysis.pattern.value} complexity={analysis.complexity}\n"
            f"reasoning:\n{analysis.reasoning or ''}\n"
            f"subtasks ({len(analysis.subtasks)}):\n{sub_block}"
        )
        await _emit_graph_node_event(
            config,
            "graph_node_exit",
            node="classify",
            duration_ms=round(classify_ms),
            output_preview=classify_summary,
        )
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
        direct_step = _make_step(
            StepType.LLM_CALL,
            "direct_shortcircuit",
            input=raw_query_str,
            output=_direct_text,
            max_length=ml,
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

    if not is_frozen:
        handler = registry.get(analysis.pattern)
        if handler is None:
            logger.warning(f"[{name}] No handler for pattern '{pattern_val}' — falling back to REACT.")
            handler = handle_react

    logger.event(f"[{name}] execute → {pattern_val}")
    assert handler is not None, "handler must be set by frozen or dynamic path"
    exec_invoke_config = {**(invoke_config or {}), "_steps": _steps}
    t_exec = time.perf_counter()
    await _emit_graph_node_event(config, "graph_node_enter", node=pattern_val, pattern=pattern_val, input_preview=augmented_query)
    handler_user_turn = merge_context_into_user_turn(augmented_query, query)
    result: ExecutionResult = await handler(config, handler_user_turn, analysis, exec_invoke_config)
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
                skill = await skill_generator.generate_for_query(query=query, tools=tools_for_gen, agent_name=name)
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

    _maybe_fire_feedback_hooks(config, result, raw_query_str, name, skill_used=analysis.matched_skill)

    for wr in result.worker_results:
        if hasattr(wr, "token_usage") and wr.token_usage:
            _total_usage = _merge_token_usage(_total_usage, wr.token_usage)
    if result.token_usage:
        _total_usage = _merge_token_usage(_total_usage, result.token_usage)

    all_steps = _steps + [s for s in result.steps if s not in _steps]

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
    return result


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
    """

    def __init__(self, config: dict) -> None:
        self.config = config

    async def __aenter__(self) -> UnifiedAgent:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Release all held resources: MCP connections, thread pools, HTTP clients."""
        if self.config.get("_mcp_client") is not None:
            try:
                await aclose_mcp_client(self.config["_mcp_client"], log_name=self.name)
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
              latency.
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
                last_n=_memory_injection_last_n(self.config),
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
                classifier_timeout=self.config.get("classifier_timeout", 60.0),
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

        emitter = SessionEmitter._callback_only(
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
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

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

        Unlike ``ainvoke``, this targets the compiled graph. Requires a ``checkpointer``
        passed to ``create_agent``.
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

    from .cli_tools import get_cli_tools, normalize_cli_tools_kwargs

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
            # Granular list — subprocess tools when ``allow_shell``; destructive FS / notebook edits.
            if cli_tools_kw.get("allow_shell", True):
                for token in (
                    "execute",
                    "bash",
                    "bash_background",
                    "bash_background_status",
                    "bash_background_stop",
                ):
                    if token not in ibi_merged:
                        ibi_merged.append(token)
            for token in (
                "write_file",
                "edit_file",
                "multi_edit",
                "delete_file",
                "move_file",
                "rmdir",
                "notebook_edit",
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
        merged = OrderedDict((t.name, t) for t in builtins)
        for t in resolved_tools:
            merged[t.name] = t
        resolved_tools = list(merged.values())

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
            except Exception:
                return fn

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
    """Synchronous wrapper for ``create_agent`` (``asyncio.run``, or thread pool if a loop runs)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(create_agent(*args, **kwargs))

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, create_agent(*args, **kwargs))
        return future.result()
