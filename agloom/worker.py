"""Single-task workers used by supervisor/swarm/pipeline patterns.

Each ``run_worker`` builds a short-lived LangChain ReAct agent (when tools exist),
runs one assignment, and returns ``WorkerResult``. Recursion/time limits align with
``patterns.react.REACT_RECURSION_LIMIT`` where applicable.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from langchain.agents import create_agent as lc_create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from .llm_streaming import stream_or_invoke_llm
from .logging_utils import get_logger
from .wire_stream_content import emit_llm_chunk_to_event_queue
from .models import (
    AgentEvent,
    AgentStep,
    ResolvedWorkerConfig,
    SignalType,
    StepType,
    WorkerResult,
    _extract_token_usage,
    _make_step,
)

logger = get_logger(__name__)

WORKER_RECURSION_LIMIT = 25

REACT_DISCIPLINE = """
TOOL USAGE RULES
- Use at most 3-5 tool calls for this task. Be targeted, not exhaustive.
- One well-formed query beats five vague ones.
- Stop searching once you have sufficient information to answer.
- Never repeat the same tool call with the same arguments.
- Synthesize and return your final answer as soon as you have enough data.

FINAL REPLY
- If tools already executed the task, reply briefly: outcomes and paths only — no step-by-step rehash of how you used tools.
""".strip()

_MEMORY_TOOLS = {"save_memory", "recall_memory"}


def _step_trunc_len(invoke_config: dict | None) -> int:
    """Per-run cap for tool step snippets (``max_step_output_length`` from agent, via invoke metadata)."""
    if not invoke_config:
        return 0
    md = invoke_config.get("metadata") or {}
    v = md.get("max_step_output_length", 0)
    if isinstance(v, int) and v >= 0:
        return v
    return 0


def resolve_event_queue(agent: dict | None, config: dict | None = None) -> Any:
    """Single precedence: explicit *config* queue, then *agent* queue."""
    if config is not None:
        eq = config.get("_event_queue")
        if eq is not None:
            return eq
    if agent is not None:
        return agent.get("_event_queue")
    return None


def extend_invoke_config_with_event_queue(
    invoke_config: dict | None, event_queue: Any, *, agent: dict | None = None
) -> dict | None:
    """Attach parent ``_event_queue`` so workers can ``astream`` to the CLI (parallel + sequential).

    When *invoke_config* omits ``configurable.signal_queue`` / ``clarification_queues`` (e.g. it was
    ``None`` and only the event queue is being merged), copy those from *agent* so L4 tools and
    the parallel HITL listener still share the parent's queues.
    """
    if event_queue is None:
        return invoke_config
    base = dict(invoke_config or {})
    base["_event_queue"] = event_queue
    if agent is not None:
        from .wire_tokens import _WIRE_EMITTED_KEY

        if _WIRE_EMITTED_KEY in agent:
            base[_WIRE_EMITTED_KEY] = agent[_WIRE_EMITTED_KEY]
    if agent is not None:
        conf = dict(base.get("configurable") or {})
        if conf.get("signal_queue") is None and agent.get("signal_queue") is not None:
            conf["signal_queue"] = agent["signal_queue"]
        if conf.get("clarification_queues") is None and agent.get("clarification_queues") is not None:
            conf["clarification_queues"] = agent["clarification_queues"]
        base["configurable"] = conf
        ibt = agent.get("interrupt_before_tools") or []
        ucb = agent.get("user_callback")
        if ibt and ucb:
            coalescer = agent.get("_hitl_tool_coalescer")
            if coalescer is None:
                from agloom.patterns.hitl_tool_coalesce import build_default_hitl_coalescer

                coalescer = build_default_hitl_coalescer()
                agent["_hitl_tool_coalescer"] = coalescer
            base["_hitl_parent"] = {
                "interrupt_before_tools": list(ibt),
                "user_callback": ucb,
                "_hitl_tool_allowlist": agent.get("_hitl_tool_allowlist"),
                "_hitl_tool_coalescer": coalescer,
                "name": agent.get("name", "UnifiedAgent"),
            }
        base["react_force_tool_choice_on_user_turn"] = agent.get(
            "react_force_tool_choice_on_user_turn", True
        )
    return base


async def run_worker(
    config: ResolvedWorkerConfig,
    llm: Any,
    invoke_config: dict | None = None,
) -> WorkerResult:
    """Run one ``ResolvedWorkerConfig``: ReAct when ``tools`` is non-empty, else a single LLM call.

    ``invoke_config`` is forwarded from ``run_fresh`` and merged in ``build_graph_config``.
    Result ``elapsed_ms`` includes retries.
    """
    t_start = time.perf_counter()

    logger.info(
        f"[{config.worker_id}] starting | "
        f"tools={[t.name for t in config.tools] if config.tools else 'LLM-only'} | "
        f"task={config.task!r}"
    )

    if config.tools:
        result = await _run_react(config, llm, invoke_config)
    else:
        result = await _run_llm_only(config, llm, invoke_config)

    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)

    result = WorkerResult(
        worker_id=result.worker_id,
        task=result.task,
        output=result.output,
        signal=result.signal,
        error=result.error,
        elapsed_ms=elapsed_ms,
        attempt=result.attempt,
        token_usage=result.token_usage,
        steps=result.steps,
        messages=result.messages,
    )

    logger.info(
        f"[{config.worker_id}] done | "
        f"signal={result.signal.value} | "
        f"elapsed_ms={elapsed_ms} | "
        f"output_chars={len(result.output)} | "
        f"attempt={result.attempt}"
    )
    return result


def _build_graph_config(
    config: ResolvedWorkerConfig,
    invoke_config: dict | None,
    mode: str,
    attempt: int,
) -> dict:
    """
    Build the RunnableConfig dict for agent.ainvoke / llm.ainvoke.

    Merges invoke_config (thread_id, memory_namespace, signal_queue).
    Drops memory_namespace when the worker has no memory tools: LangGraph
    crashes if that key is set without a matching store.
    Sets run_name and metadata for LangSmith trace labels and filtering.
    """
    base = dict(invoke_config or {})

    tool_names = {t.name for t in config.tools}
    has_memory = bool(tool_names & _MEMORY_TOOLS)

    if not has_memory and "configurable" in base:
        cleaned = {k: v for k, v in base["configurable"].items() if k != "memory_namespace"}
        base["configurable"] = cleaned

    task_preview = config.task.replace("\n", " ")
    attempt_label = f" (attempt {attempt})" if attempt > 1 else ""
    run_name = f"{config.worker_id} | {task_preview} | {mode}{attempt_label}"

    base["run_name"] = run_name
    base["metadata"] = {
        **(base.get("metadata") or {}),
        "worker_id": config.worker_id,
        "task": config.task,
        "mode": mode,
        "attempt": attempt,
        "tools": sorted(tool_names),
        "depends_on": config.depends_on,
    }

    base["recursion_limit"] = WORKER_RECURSION_LIMIT

    return base


async def _react_graph_astream_to_result(
    config: ResolvedWorkerConfig,
    lc_agent: Any,
    task_content: str,
    graph_config: dict,
    event_queue: asyncio.Queue,
) -> dict[str, Any]:
    """Run worker ReAct graph with ``astream_events`` so tokens/tools stream to the CLI."""
    state: dict[str, Any] = {"messages": [HumanMessage(content=task_content)]}
    final_response: dict[str, Any] | None = None
    _tool_run_ids: dict[str, str] = {}
    _tool_arg_dicts: dict[str, dict[str, Any]] = {}
    wid = config.worker_id

    async for event in lc_agent.astream_events(
        state,
        config=cast("RunnableConfig", graph_config),
        version="v2",
    ):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            reasoning, answer = await emit_llm_chunk_to_event_queue(
                event_queue, chunk, worker_id=wid
            )
            _ = reasoning, answer
        elif kind == "on_tool_start":
            run_id = str(event.get("run_id", ""))
            tool_name = event.get("name", "unknown")
            tool_input = event.get("data", {}).get("input", {})
            arg_dict = tool_input if isinstance(tool_input, dict) else {"input": str(tool_input)}
            _tool_arg_dicts[run_id] = arg_dict
            _tool_run_ids[run_id] = tool_name
            await event_queue.put(
                AgentEvent(
                    type="tool_call",
                    data={
                        "id": run_id,
                        "name": tool_name,
                        "args": arg_dict,
                        "worker_id": wid,
                    },
                )
            )
        elif kind == "on_tool_end":
            run_id = str(event.get("run_id", ""))
            tool_name = _tool_run_ids.pop(run_id, event.get("name", "unknown"))
            raw_out = event.get("data", {}).get("output")
            args_rem = _tool_arg_dicts.pop(run_id, {})
            skill_name: str | None = None
            if tool_name == "load_skill":
                n = args_rem.get("name")
                skill_name = n if isinstance(n, str) else None
            if isinstance(raw_out, dict) and isinstance(raw_out.get("summary"), str):
                out_payload: str | dict[str, object] = raw_out
            else:
                out_payload = str(raw_out or "")
            await event_queue.put(
                AgentEvent(
                    type="tool_result",
                    data={
                        "id": run_id,
                        "name": tool_name,
                        "output": out_payload,
                        "worker_id": wid,
                        "args": args_rem,
                        **({"skill_name": skill_name} if skill_name else {}),
                    },
                )
            )
        elif kind == "on_chain_end":
            output_data = event.get("data", {}).get("output")
            if isinstance(output_data, dict) and "messages" in output_data:
                final_response = output_data

    if final_response is None:
        raise ValueError("astream_events finished without a messages state")
    return final_response


def _worker_react_middleware(invoke_config: dict | None, worker_id: str) -> list[Any]:
    """Tool-choice + L2 HITL middleware for supervisor/reflection/swarm worker ReAct agents."""
    from agloom.patterns.middleware import build_langchain_agent_middleware

    force = True
    if invoke_config is not None:
        force = bool(invoke_config.get("react_force_tool_choice_on_user_turn", True))
    return build_langchain_agent_middleware(
        force_tool_choice_on_user_turn=force,
        extras=_hitl_middleware_for_invoke(invoke_config, worker_id),
    )


def _hitl_middleware_for_invoke(invoke_config: dict | None, worker_id: str) -> list[Any]:
    """Share parent L2 HITL (allowlist + coalescer) for supervisor/swarm worker ReAct agents."""
    if not invoke_config:
        return []
    parent = invoke_config.get("_hitl_parent")
    if not isinstance(parent, dict):
        return []
    ibt = parent.get("interrupt_before_tools") or []
    ucb = parent.get("user_callback")
    if not ibt or not ucb:
        return []
    from agloom.patterns.middleware import HumanApprovalMiddleware
    from agloom.patterns.hitl_tool_coalesce import build_default_hitl_coalescer

    coalescer = parent.get("_hitl_tool_coalescer")
    if coalescer is None:
        coalescer = build_default_hitl_coalescer()
        parent["_hitl_tool_coalescer"] = coalescer
    parent_name = parent.get("name") or "Agent"
    return [
        HumanApprovalMiddleware(
            interrupt_before_tools=list(ibt),
            user_callback=ucb,
            agent_name=f"{parent_name}:{worker_id}",
            tool_allowlist=parent.get("_hitl_tool_allowlist"),
            hitl_coalescer=coalescer,
        )
    ]


async def _run_react(
    config: ResolvedWorkerConfig,
    llm: Any,
    invoke_config: dict | None,
) -> WorkerResult:
    """
    ReAct execution via langchain.agents.create_agent (LangChain 1.0).

    Each retry creates a FRESH agent — ephemeral by design.
    Each worker gets its own InMemorySaver — enables L2 interrupt inside tools.
    The saver is discarded with the worker → no state leaks.
    """
    for attempt in range(1, config.max_retries + 2):
        t_attempt = time.perf_counter()
        try:
            single_tool_hint = ""
            if len(config.tools) == 1:
                single_tool_hint = (
                    f"\n- Single-tool step: call {config.tools[0].name} at most ONCE "
                    f"with the text to process, then reply with the final answer as plain text."
                )

            hitl_middleware = _worker_react_middleware(invoke_config, config.worker_id)
            agent = lc_create_agent(
                model=llm,
                tools=config.tools,
                system_prompt=config.system_prompt.rstrip() + "\n" + REACT_DISCIPLINE + single_tool_hint,
                name=config.worker_id,
                checkpointer=InMemorySaver(),
                middleware=hitl_middleware,
            )

            task_content = config.task
            if config.context:
                ctx_str = "\n".join(f"{k}: {v}" for k, v in config.context.items())
                task_content = f"Context:\n{ctx_str}\n\n{config.task}"

            graph_config = _build_graph_config(config, invoke_config, "ReAct", attempt)
            eq = (invoke_config or {}).get("_event_queue")
            from .llm_utils import DEFAULT_LLM_SEMAPHORE, _circuit_breaker_for

            async def _invoke_react() -> dict:
                if eq is not None:
                    return await _react_graph_astream_to_result(
                        config, agent, task_content, graph_config, eq
                    )
                return await cast(Any, agent).ainvoke(
                    {"messages": [HumanMessage(content=task_content)]},
                    config=graph_config,
                )

            async with _circuit_breaker_for(llm), DEFAULT_LLM_SEMAPHORE:
                result = await asyncio.wait_for(_invoke_react(), timeout=config.llm_timeout)
            output, usage = _extract_output(result)
            if usage and invoke_config is not None:
                from .wire_tokens import emit_llm_call_usage, llm_label_from_run_config

                await emit_llm_call_usage(
                    invoke_config,
                    usage,
                    phase=config.worker_id,
                    model=llm_label_from_run_config(invoke_config),
                    name=config.worker_id,
                )
            tool_steps = _extract_tool_steps(
                result,
                max_length=_step_trunc_len(invoke_config),
                wire_emitted=eq is not None,
            )

            attempt_ms = round((time.perf_counter() - t_attempt) * 1000, 1)
            logger.info(
                f"[{config.worker_id}] ReAct attempt {attempt} ok | "
                f"attempt_ms={attempt_ms} | output_chars={len(output)} | "
                f"tool_steps={len(tool_steps)}"
            )
            return WorkerResult(
                worker_id=config.worker_id,
                task=config.task,
                output=output,
                signal=SignalType.SUCCESS,
                attempt=attempt,
                token_usage=usage,
                steps=tool_steps,
                messages=result.get("messages", []),
            )

        except TimeoutError:
            logger.warning(f"[{config.worker_id}] timeout after {config.llm_timeout}s.")
            return WorkerResult(
                worker_id=config.worker_id,
                task=config.task,
                output=f"Worker timed out after {config.llm_timeout} seconds.",
                signal=SignalType.FAILED,
                error="TimeoutError",
                attempt=attempt,
            )

        except asyncio.CancelledError:
            logger.warning(f"[{config.worker_id}] cancelled.")
            raise

        except GraphRecursionError as e:
            logger.error(f"[{config.worker_id}] recursion limit {WORKER_RECURSION_LIMIT} — not retrying. {e}")
            return WorkerResult(
                worker_id=config.worker_id,
                task=config.task,
                output=f"Recursion limit reached: {e}",
                signal=SignalType.FAILED,
                error=str(e),
                attempt=attempt,
            )

        except Exception as e:
            if attempt > config.max_retries:
                logger.error(f"[{config.worker_id}] failed after {attempt} attempts: {e}")
                return WorkerResult(
                    worker_id=config.worker_id,
                    task=config.task,
                    output=f"Worker failed after {attempt} attempts: {e}",
                    signal=SignalType.FAILED,
                    error=str(e),
                    attempt=attempt,
                )
            logger.warning(f"[{config.worker_id}] attempt {attempt} failed: {e} — retrying in {config.retry_delay}s")
            await asyncio.sleep(config.retry_delay)

    return WorkerResult(
        worker_id=config.worker_id,
        task=config.task,
        output="Worker exhausted all retries without a result.",
        signal=SignalType.FAILED,
        error="ExhaustedRetries",
        attempt=config.max_retries + 1,
    )


async def _run_llm_only(
    config: ResolvedWorkerConfig,
    llm: Any,
    invoke_config: dict | None = None,
) -> WorkerResult:
    """
    Direct LLM call — no graph, no recursion risk.
    Used when worker has no tools (intentional or required tools not in registry).

    LangSmith span: llm.with_config(run_name=...) names the ChatModel span
    so it appears as "worker-3 | Translate text | LLM-only" in traces
    instead of the default "ChatNVIDIA" / "ChatOpenAI".
    """
    for attempt in range(1, config.max_retries + 2):
        t_attempt = time.perf_counter()
        try:
            task_content = config.task
            if config.context:
                ctx_str = "\n".join(f"{k}: {v}" for k, v in config.context.items())
                task_content = f"Context:\n{ctx_str}\n\n{config.task}"

            # with_config() does not mutate the shared llm instance (safe under concurrency).
            task_preview = config.task.replace("\n", " ")
            named_llm = llm.with_config(
                run_name=f"{config.worker_id} | {task_preview} | LLM-only",
                metadata={
                    "worker_id": config.worker_id,
                    "task": config.task,
                    "mode": "LLM-only",
                    "attempt": attempt,
                },
            )

            input_msgs = [
                SystemMessage(content=config.system_prompt),
                HumanMessage(content=task_content),
            ]
            base_cfg = invoke_config or {}
            configurable = dict(base_cfg.get("configurable") or {})
            stream_agent = {**base_cfg, "configurable": configurable, "llm": llm}
            output, _tail_msgs, last_chunk = await stream_or_invoke_llm(
                named_llm,
                input_msgs,
                stream_agent,
                timeout=config.llm_timeout,
                worker_id=config.worker_id,
                phase=config.worker_id,
            )
            usage = _extract_token_usage(last_chunk) if last_chunk else {}
            tail = last_chunk if last_chunk is not None else AIMessage(content=output)

            attempt_ms = round((time.perf_counter() - t_attempt) * 1000, 1)
            logger.info(
                f"[{config.worker_id}] LLM-only attempt {attempt} ok | "
                f"attempt_ms={attempt_ms} | output_chars={len(output)}"
            )
            return WorkerResult(
                worker_id=config.worker_id,
                task=config.task,
                output=output,
                signal=SignalType.SUCCESS,
                attempt=attempt,
                token_usage=usage,
                messages=input_msgs + [tail],
            )

        except TimeoutError:
            logger.warning(f"[{config.worker_id}] timeout after {config.llm_timeout}s.")
            return WorkerResult(
                worker_id=config.worker_id,
                task=config.task,
                output=f"Worker timed out after {config.llm_timeout} seconds.",
                signal=SignalType.FAILED,
                error="TimeoutError",
                attempt=attempt,
            )

        except asyncio.CancelledError:
            logger.warning(f"[{config.worker_id}] cancelled.")
            raise

        except Exception as e:
            if attempt > config.max_retries:
                logger.error(f"[{config.worker_id}] failed after {attempt} attempts: {e}")
                return WorkerResult(
                    worker_id=config.worker_id,
                    task=config.task,
                    output=f"Worker failed after {attempt} attempts: {e}",
                    signal=SignalType.FAILED,
                    error=str(e),
                    attempt=attempt,
                )
            logger.warning(f"[{config.worker_id}] attempt {attempt} failed: {e} — retrying in {config.retry_delay}s")
            await asyncio.sleep(config.retry_delay)

    return WorkerResult(
        worker_id=config.worker_id,
        task=config.task,
        output="Worker exhausted all retries without a result.",
        signal=SignalType.FAILED,
        error="ExhaustedRetries",
        attempt=config.max_retries + 1,
    )


def _extract_tool_steps(
    result: Any, *, max_length: int = 0, wire_emitted: bool = False
) -> list[AgentStep]:
    """Extract tool_call/tool_result steps from a LangGraph ainvoke response."""
    if not isinstance(result, dict):
        return []
    from langchain_core.messages import ToolMessage

    steps: list[AgentStep] = []
    for msg in result.get("messages", []):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                steps.append(
                    _make_step(
                        StepType.TOOL_CALL,
                        tc.get("name", "unknown"),
                        input=str(tc.get("args", "")),
                        id=tc.get("id", ""),
                        max_length=max_length,
                        wire_emitted=wire_emitted,
                    )
                )
        elif isinstance(msg, ToolMessage):
            steps.append(
                _make_step(
                    StepType.TOOL_RESULT,
                    msg.name or "unknown",
                    output=str(msg.content),
                    id=getattr(msg, "tool_call_id", "") or "",
                    max_length=max_length,
                    wire_emitted=wire_emitted,
                )
            )
    return steps


def _extract_output(result: Any) -> tuple[str, dict[str, int]]:
    """
    Extract final text and token usage from create_agent ainvoke result.
    Returns (output_text, token_usage_dict).
    """
    usage = _extract_token_usage(result)

    if isinstance(result, dict) and "messages" in result:
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                content = msg.content
                return (content if isinstance(content, str) else str(content)), usage
        messages = result["messages"]
        if messages:
            last = messages[-1]
            if hasattr(last, "content"):
                content = last.content
                return (content if isinstance(content, str) else str(content)), usage
            return str(last), usage

    if isinstance(result, str):
        return result, usage
    if isinstance(result, AIMessage):
        content = result.content
        return (content if isinstance(content, str) else str(content)), usage
    return (str(result) if result else "No output produced."), usage
