"""ReAct pattern — single agent + tool-calling loop with optional L2 HITL."""

import asyncio
import time
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError

from ..logging_utils import get_logger
from ..models import (
    AgentEvent,
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    StepType,
    _extract_token_usage,
    _make_step,
)
from .middleware import HumanApprovalMiddleware, UserAbort

logger = get_logger(__name__)


REACT_RECURSION_LIMIT = 25
REACT_MAX_HITL_CYCLES = REACT_RECURSION_LIMIT // 2

_TOOL_USE_FAILED = "tool_use_failed"
_MAX_TOOL_RETRIES = 3
_RETRY_DELAY = 0.5
_AINVOKE_TIMEOUT = 120  # cap waits so stuck LLM/tool calls cannot block forever


REACT_TOOL_DISCIPLINE = """

=== TOOL USAGE RULES ===
- Call each tool ONCE per task — do not repeat the same tool call.
- After receiving a tool result, synthesize and respond IMMEDIATELY.
- Do NOT call more tools unless the result explicitly requires it.
- Return your final answer right after getting the tool output.\
"""


async def handle_react(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """
    Run a ReAct agent: tool loop with retry on malformed tool calls,
    optional L2 HITL via HumanApprovalMiddleware, and timeout protection.
    Falls back to direct LLM call when no tools are available.
    """
    llm = agent["llm"]
    tools = agent["tools"]
    system_prompt = agent["system_prompt"] + REACT_TOOL_DISCIPLINE
    name = agent.get("name", "UnifiedAgent")
    interrupt_before_tools = agent.get("interrupt_before_tools", [])
    user_callback = agent.get("user_callback")
    steps: list = (config or {}).get("_steps", [])

    hitl_active = bool(interrupt_before_tools and user_callback)

    logger.event(f"[React] ▶ {name} — {len(tools)} tools available | HITL={'Level2-Tool' if hitl_active else 'off'}")

    if not tools:
        logger.debug("[React] No tools — direct LLM fallback.")
        t0 = time.perf_counter()
        resp = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content=agent["system_prompt"]),
                    HumanMessage(content=query),
                ]
            ),
            timeout=_AINVOKE_TIMEOUT,
        )
        dur = round((time.perf_counter() - t0) * 1000, 1)
        usage = _extract_token_usage(resp)
        steps.append(
            _make_step(
                StepType.LLM_CALL,
                "react_fallback_llm",
                input=query[:200],
                output=resp.content[:200],
                duration_ms=dur,
            )
        )
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=resp.content,
            steps_taken=1,
            success=True,
            analysis=analysis,
            steps=steps,
            token_usage=usage,
        )

    if hitl_active:
        return await _handle_react_hitl(
            llm=llm,
            tools=tools,
            system_prompt=system_prompt,
            query=query,
            analysis=analysis,
            name=name,
            interrupt_before_tools=interrupt_before_tools,
            user_callback=user_callback,
            incoming_config=config,
        )

    event_queue = agent.get("_event_queue")
    if event_queue is not None:
        return await _handle_react_streaming(
            agent=agent,
            query=query,
            analysis=analysis,
            config=config,
            event_queue=event_queue,
        )

    react_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )

    invoke_config = {
        **(config or {}),
        "recursion_limit": REACT_RECURSION_LIMIT,
    }

    state = {"messages": [{"role": "user", "content": query}]}
    response = None

    for attempt in range(1, _MAX_TOOL_RETRIES + 1):
        try:
            t0 = time.perf_counter()
            response = await asyncio.wait_for(
                react_agent.ainvoke(state, config=invoke_config),  # type: ignore[arg-type]
                timeout=_AINVOKE_TIMEOUT,
            )
            dur = round((time.perf_counter() - t0) * 1000, 1)

            output = _extract_last_ai_message(response)
            if not output:
                output = "No output produced."

            usage = _extract_token_usage(response)
            _collect_tool_steps(response, steps)
            steps.append(
                _make_step(
                    StepType.LLM_CALL,
                    "react_agent",
                    input=query[:200],
                    output=output[:200],
                    duration_ms=dur,
                    messages=len(response.get("messages", [])),
                )
            )

            logger.event(f"[React] ✅ Done — {len(response['messages'])} messages exchanged.")
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=output,
                steps_taken=2,
                success=True,
                analysis=analysis,
                steps=steps,
                token_usage=usage,
            )

        except GraphRecursionError:
            logger.warning(f"[React] ⚠ Recursion limit ({REACT_RECURSION_LIMIT}) reached.")
            partial = "Step limit reached — partial result may be incomplete."
            try:
                partial = _extract_last_ai_message(response) or partial
            except Exception:
                pass
            steps.append(_make_step(StepType.FALLBACK, "react_recursion_limit", output=partial[:200]))
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=partial,
                steps_taken=REACT_RECURSION_LIMIT,
                success=True,
                analysis=analysis,
                steps=steps,
            )

        except Exception as exc:
            if _TOOL_USE_FAILED in str(exc) and attempt < _MAX_TOOL_RETRIES:
                logger.warning(
                    f"[React] ⚠ tool_use_failed on attempt "
                    f"{attempt}/{_MAX_TOOL_RETRIES} (agent={name}) "
                    f"— retrying in {_RETRY_DELAY}s."
                )
                await asyncio.sleep(_RETRY_DELAY)
                state = {
                    "messages": state["messages"]
                    + [
                        HumanMessage(
                            content=(
                                "Your previous tool call was malformed. Please try the tool call again with valid JSON."
                            )
                        )
                    ]
                }
                continue

            logger.error(f"[React] ❌ Failed: {exc}")
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=f"REACT execution failed: {exc}",
                steps_taken=attempt,
                success=False,
                analysis=analysis,
                steps=steps,
            )

    return ExecutionResult(
        pattern_used=PatternType.REACT,
        query=query,
        output="REACT exhausted all retries without a result.",
        steps_taken=_MAX_TOOL_RETRIES,
        success=False,
        analysis=analysis,
        steps=steps,
    )


async def _handle_react_streaming(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
    event_queue: asyncio.Queue | None = None,
) -> ExecutionResult:
    """REACT with live token-by-token streaming via LangGraph astream_events.

    Uses the LangGraph agent's astream_events(version="v2") to capture:
    - on_chat_model_stream: individual LLM tokens → pushed as "token" events
    - on_tool_start: tool invocations → pushed as "tool_call" events with id
    - on_tool_end: tool results → pushed as "tool_result" events with matching id
    - on_chain_end: final state for response extraction

    Falls back to the standard ainvoke path if astream_events is unavailable.
    """
    llm = agent["llm"]
    tools = agent["tools"]
    system_prompt = agent["system_prompt"] + REACT_TOOL_DISCIPLINE
    name = agent.get("name", "UnifiedAgent")
    steps: list = (config or {}).get("_steps", [])

    react_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )

    invoke_config = {
        **(config or {}),
        "recursion_limit": REACT_RECURSION_LIMIT,
    }
    state = {"messages": [{"role": "user", "content": query}]}

    t0 = time.perf_counter()
    final_response = None
    _tool_run_ids: dict[str, str] = {}

    try:
        async for event in react_agent.astream_events(state, config=invoke_config, version="v2"):
            kind = event["event"]

            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                content = getattr(chunk, "content", "")
                if content:
                    content = content if isinstance(content, str) else str(content)
                    if event_queue:
                        await event_queue.put(AgentEvent(type="token", data={"content": content}))

            elif kind == "on_tool_start":
                run_id = str(event.get("run_id", ""))
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                _tool_run_ids[run_id] = tool_name
                if event_queue:
                    await event_queue.put(
                        AgentEvent(
                            type="tool_call",
                            data={
                                "id": run_id,
                                "name": tool_name,
                                "input": str(tool_input)[:200],
                            },
                        )
                    )
                steps.append(
                    _make_step(
                        StepType.TOOL_CALL,
                        tool_name,
                        input=str(tool_input)[:200],
                        id=run_id,
                    )
                )

            elif kind == "on_tool_end":
                run_id = str(event.get("run_id", ""))
                tool_name = _tool_run_ids.pop(run_id, event.get("name", "unknown"))
                tool_output = str(event.get("data", {}).get("output", ""))
                if event_queue:
                    await event_queue.put(
                        AgentEvent(
                            type="tool_result",
                            data={
                                "id": run_id,
                                "name": tool_name,
                                "output": tool_output[:200],
                            },
                        )
                    )
                steps.append(
                    _make_step(
                        StepType.TOOL_RESULT,
                        tool_name,
                        output=tool_output[:200],
                        id=run_id,
                    )
                )

            elif kind == "on_chain_end":
                output_data = event.get("data", {}).get("output")
                if isinstance(output_data, dict) and "messages" in output_data:
                    final_response = output_data

        dur = round((time.perf_counter() - t0) * 1000, 1)
        output = _extract_last_ai_message(final_response)
        if not output:
            output = "No output produced."

        usage = _extract_token_usage(final_response)
        steps.append(
            _make_step(
                StepType.LLM_CALL,
                "react_agent",
                input=query[:200],
                output=output[:200],
                duration_ms=dur,
                messages=len((final_response or {}).get("messages", [])),
            )
        )

        logger.event(f"[React|stream] Done — {len((final_response or {}).get('messages', []))} messages.")
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=output,
            steps_taken=2,
            success=True,
            analysis=analysis,
            steps=steps,
            token_usage=usage,
        )

    except GraphRecursionError:
        logger.warning(f"[React|stream] Recursion limit ({REACT_RECURSION_LIMIT}) reached.")
        partial = "Step limit reached — partial result may be incomplete."
        try:
            partial = _extract_last_ai_message(final_response) or partial
        except Exception:
            pass
        steps.append(_make_step(StepType.FALLBACK, "react_recursion_limit", output=partial[:200]))
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=partial,
            steps_taken=REACT_RECURSION_LIMIT,
            success=True,
            analysis=analysis,
            steps=steps,
        )

    except Exception as exc:
        logger.error(f"[React|stream] Failed: {exc}")
        logger.debug(f"[React|stream] Falling back to ainvoke for {name}")
        return await _handle_react_ainvoke_fallback(
            agent=agent,
            query=query,
            analysis=analysis,
            config=config,
        )


async def _handle_react_ainvoke_fallback(
    agent: dict,
    query: str,
    analysis: QueryAnalysis,
    config: dict | None = None,
) -> ExecutionResult:
    """Fallback to standard ainvoke when streaming is unavailable."""
    llm = agent["llm"]
    tools = agent["tools"]
    system_prompt = agent["system_prompt"] + REACT_TOOL_DISCIPLINE
    steps: list = (config or {}).get("_steps", [])

    react_agent = create_agent(model=llm, tools=tools, system_prompt=system_prompt)
    invoke_config = {**(config or {}), "recursion_limit": REACT_RECURSION_LIMIT}
    state = {"messages": [{"role": "user", "content": query}]}

    try:
        t0 = time.perf_counter()
        response = await asyncio.wait_for(
            react_agent.ainvoke(state, config=invoke_config),
            timeout=_AINVOKE_TIMEOUT,
        )
        dur = round((time.perf_counter() - t0) * 1000, 1)
        output = _extract_last_ai_message(response) or "No output produced."
        usage = _extract_token_usage(response)
        _collect_tool_steps(response, steps)
        steps.append(
            _make_step(
                StepType.LLM_CALL,
                "react_agent",
                input=query[:200],
                output=output[:200],
                duration_ms=dur,
            )
        )
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=output,
            steps_taken=2,
            success=True,
            analysis=analysis,
            steps=steps,
            token_usage=usage,
        )
    except Exception as exc:
        logger.error(f"[React|fallback] Failed: {exc}")
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=f"REACT execution failed: {exc}",
            steps_taken=1,
            success=False,
            analysis=analysis,
            steps=steps,
        )


async def _handle_react_hitl(
    llm,
    tools: list,
    system_prompt: str,
    query: str,
    analysis: QueryAnalysis,
    name: str,
    interrupt_before_tools: list[str],
    user_callback: Any,
    incoming_config: dict | None = None,
) -> ExecutionResult:
    """L2 HITL path — HumanApprovalMiddleware intercepts tool calls inline."""
    approval_middleware = HumanApprovalMiddleware(
        interrupt_before_tools=interrupt_before_tools,
        user_callback=user_callback,
        agent_name=name,
    )

    react_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=[approval_middleware],
    )

    invoke_config = {
        **(incoming_config or {}),
        "recursion_limit": REACT_RECURSION_LIMIT,
    }
    response = None

    try:
        response = await asyncio.wait_for(
            react_agent.ainvoke(  # type: ignore[no-matching-overload]
                {"messages": [{"role": "user", "content": query}]},
                config=invoke_config,
            ),
            timeout=_AINVOKE_TIMEOUT,
        )
        output = _extract_last_ai_message(response)
        if not output:
            output = "No output produced."

        logger.event(f"[React|HITL] ✅ Done — {len(output)} chars.")
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=output,
            steps_taken=2,
            success=True,
            analysis=analysis,
        )

    except UserAbort:
        logger.event("[React|HITL] ✋ Aborted by user.")
        partial = "Aborted before tool execution."
        try:
            partial = _extract_last_ai_message(response) or partial
        except Exception:
            pass
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=partial,
            steps_taken=1,
            success=True,  # deliberate user action, not a failure
            analysis=analysis,
        )

    except GraphRecursionError:
        logger.warning(f"[React|HITL] ⚠ Recursion limit ({REACT_RECURSION_LIMIT}) reached.")
        partial = "Step limit reached — partial result may be incomplete."
        try:
            partial = _extract_last_ai_message(response) or partial
        except Exception:
            pass
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=partial,
            steps_taken=REACT_RECURSION_LIMIT,
            success=True,
            analysis=analysis,
        )

    except Exception as exc:
        logger.error(f"[React|HITL] ❌ Failed: {exc}")
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=f"REACT HITL execution failed: {exc}",
            steps_taken=1,
            success=False,
            analysis=analysis,
        )


def _collect_tool_steps(response: dict | None, steps: list) -> None:
    """Scan response messages for tool calls/results and append steps.

    Extracts tool_call_id from LangChain messages so callers can correlate
    which tool_result belongs to which tool_call (essential for parallel
    tool execution tracking and UI spinners).
    """
    if not isinstance(response, dict):
        return
    from langchain_core.messages import ToolMessage

    for msg in response.get("messages", []):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                steps.append(
                    _make_step(
                        StepType.TOOL_CALL,
                        tc.get("name", "unknown"),
                        input=str(tc.get("args", ""))[:200],
                        id=tc.get("id", ""),
                    )
                )
        elif isinstance(msg, ToolMessage):
            steps.append(
                _make_step(
                    StepType.TOOL_RESULT,
                    msg.name or "unknown",
                    output=str(msg.content)[:200],
                    id=getattr(msg, "tool_call_id", "") or "",
                )
            )


def _extract_last_ai_message(response: dict | None) -> str:
    """Walk messages in reverse — return first AIMessage with content and no pending tool_calls."""
    if not isinstance(response, dict):
        return ""
    for msg in reversed(response.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            content = msg.content
            return content if isinstance(content, str) else str(content)
    return ""
