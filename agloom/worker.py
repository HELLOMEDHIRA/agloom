"""Single-task workers used by supervisor/swarm/pipeline patterns.

Each ``run_worker`` builds a short-lived LangChain ReAct agent (when tools exist),
runs one assignment, and returns ``WorkerResult``. Recursion/time limits align with
``patterns.react.REACT_RECURSION_LIMIT`` where applicable.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from .logging_utils import get_logger
from .llm_streaming import astream_llm_to_event_queue
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


def extend_invoke_config_with_event_queue(invoke_config: dict | None, event_queue: Any) -> dict | None:
    """Attach parent ``_event_queue`` so workers can ``astream`` to the CLI (parallel + sequential)."""
    if event_queue is None:
        return invoke_config
    base = dict(invoke_config or {})
    base["_event_queue"] = event_queue
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
        f"task={config.task[:60]!r}"
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

    task_preview = config.task[:40].replace("\n", " ")
    attempt_label = f" (attempt {attempt})" if attempt > 1 else ""
    run_name = f"{config.worker_id} | {task_preview} | {mode}{attempt_label}"

    base["run_name"] = run_name
    base["metadata"] = {
        **(base.get("metadata") or {}),
        "worker_id": config.worker_id,
        "task": config.task[:120],
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
    wid = config.worker_id

    async for event in lc_agent.astream_events(
        state,
        config=cast(RunnableConfig, graph_config),
        version="v2",
    ):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            content = getattr(chunk, "content", "")
            if content:
                c = content if isinstance(content, str) else str(content)
                await event_queue.put(
                    AgentEvent(type="token", data={"content": c, "worker_id": wid})
                )
        elif kind == "on_tool_start":
            run_id = str(event.get("run_id", ""))
            tool_name = event.get("name", "unknown")
            tool_input = event.get("data", {}).get("input", {})
            _tool_run_ids[run_id] = tool_name
            await event_queue.put(
                AgentEvent(
                    type="tool_call",
                    data={
                        "id": run_id,
                        "name": tool_name,
                        "input": str(tool_input),
                        "worker_id": wid,
                    },
                )
            )
        elif kind == "on_tool_end":
            run_id = str(event.get("run_id", ""))
            tool_name = _tool_run_ids.pop(run_id, event.get("name", "unknown"))
            tool_output = str(event.get("data", {}).get("output", ""))
            await event_queue.put(
                AgentEvent(
                    type="tool_result",
                    data={
                        "id": run_id,
                        "name": tool_name,
                        "output": tool_output,
                        "worker_id": wid,
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

            agent = create_agent(
                model=llm,
                tools=config.tools,
                system_prompt=config.system_prompt.rstrip() + "\n" + REACT_DISCIPLINE + single_tool_hint,
                name=config.worker_id,
                checkpointer=InMemorySaver(),
            )

            task_content = config.task
            if config.context:
                ctx_str = "\n".join(f"{k}: {v}" for k, v in config.context.items())
                task_content = f"Context:\n{ctx_str}\n\n{config.task}"

            graph_config = _build_graph_config(config, invoke_config, "ReAct", attempt)
            eq = (invoke_config or {}).get("_event_queue")
            if eq is not None:
                result = await asyncio.wait_for(
                    _react_graph_astream_to_result(
                        config, agent, task_content, graph_config, eq
                    ),
                    timeout=config.llm_timeout,
                )
            else:
                result = await asyncio.wait_for(
                    agent.ainvoke(  # type: ignore[no-matching-overload]
                        {"messages": [HumanMessage(content=task_content)]},
                        config=graph_config,
                    ),
                    timeout=config.llm_timeout,
                )
            output, usage = _extract_output(result)
            tool_steps = _extract_tool_steps(result)

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
            logger.warning(f"[{config.worker_id}] cancelled by HALT_ALL.")
            return WorkerResult(
                worker_id=config.worker_id,
                task=config.task,
                output="Worker cancelled by HALT_ALL signal.",
                signal=SignalType.FAILED,
                error="CancelledError",
                attempt=attempt,
            )

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
            task_preview = config.task[:40].replace("\n", " ")
            named_llm = llm.with_config(
                run_name=f"{config.worker_id} | {task_preview} | LLM-only",
                metadata={
                    "worker_id": config.worker_id,
                    "task": config.task[:120],
                    "mode": "LLM-only",
                    "attempt": attempt,
                },
            )

            input_msgs = [
                SystemMessage(content=config.system_prompt),
                HumanMessage(content=task_content),
            ]
            eq = (invoke_config or {}).get("_event_queue")
            if eq is not None:
                output, last_chunk = await astream_llm_to_event_queue(
                    named_llm,
                    input_msgs,
                    eq,
                    timeout=config.llm_timeout,
                    worker_id=config.worker_id,
                )
                usage = _extract_token_usage(last_chunk) if last_chunk else {}
                tail = last_chunk if last_chunk is not None else AIMessage(content=output)
            else:
                resp = await asyncio.wait_for(
                    named_llm.ainvoke(input_msgs),
                    timeout=config.llm_timeout,
                )
                output = resp.content
                usage = _extract_token_usage(resp)
                tail = resp

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
            logger.warning(f"[{config.worker_id}] cancelled by HALT_ALL.")
            return WorkerResult(
                worker_id=config.worker_id,
                task=config.task,
                output="Worker cancelled by HALT_ALL signal.",
                signal=SignalType.FAILED,
                error="CancelledError",
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


def _extract_tool_steps(result: Any, *, max_length: int = 0) -> list[AgentStep]:
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
