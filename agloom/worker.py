"""Ephemeral worker — create, execute, return, GC destroys."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError

from .logging_utils import get_logger
from .models import ResolvedWorkerConfig, SignalType, WorkerResult, _extract_token_usage

logger = get_logger(__name__)

# LangGraph super-steps; keep aligned with REACT_RECURSION_LIMIT in patterns/react.py
WORKER_RECURSION_LIMIT = 25
WORKER_AINVOKE_TIMEOUT = 120  # bound blocking on provider HTTP; avoids indefinite hang

REACT_DISCIPLINE = """
TOOL USAGE RULES
- Use at most 3-5 tool calls for this task. Be targeted, not exhaustive.
- One well-formed query beats five vague ones.
- Stop searching once you have sufficient information to answer.
- Never repeat the same tool call with the same arguments.
- Synthesize and return your final answer as soon as you have enough data.
""".strip()

_MEMORY_TOOLS = {"save_memory", "recall_memory"}


async def run_worker(
    config: ResolvedWorkerConfig,
    llm: Any,
    invoke_config: dict | None = None,
) -> WorkerResult:
    """
    Route to run_react (tools) or run_llm_only (no tools).

    invoke_config flow:
      run_fresh builds configurable{thread_id, memory_namespace, signal_queue}
      → forwarded to every pattern handler → forwarded here
      → merged (not replaced) into graph.ainvoke via build_graph_config()

    Metrics:
      elapsed_ms is measured at this layer — covers the full worker lifetime
      including retries. Individual attempt timing is logged inside each mode.
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
            result = await asyncio.wait_for(
                agent.ainvoke(  # type: ignore[no-matching-overload]
                    {"messages": [HumanMessage(content=task_content)]},
                    config=graph_config,
                ),
                timeout=WORKER_AINVOKE_TIMEOUT,
            )
            output, usage = _extract_output(result)

            attempt_ms = round((time.perf_counter() - t_attempt) * 1000, 1)
            logger.info(
                f"[{config.worker_id}] ReAct attempt {attempt} ok | "
                f"attempt_ms={attempt_ms} | output_chars={len(output)}"
            )
            return WorkerResult(
                worker_id=config.worker_id,
                task=config.task,
                output=output,
                signal=SignalType.SUCCESS,
                attempt=attempt,
                token_usage=usage,
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

            resp = await asyncio.wait_for(
                named_llm.ainvoke(
                    [
                        SystemMessage(content=config.system_prompt),
                        HumanMessage(content=task_content),
                    ]
                ),
                timeout=WORKER_AINVOKE_TIMEOUT,
            )
            output = resp.content
            usage = _extract_token_usage(resp)

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
