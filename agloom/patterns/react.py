"""ReAct pattern — single agent + tool-calling loop with optional L2 HITL."""

import asyncio
import time
from typing import Any, cast

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
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
    _trunc,
)
from .middleware import HumanApprovalMiddleware, ReactUserTurnToolChoiceMiddleware, UserAbort

logger = get_logger(__name__)


REACT_RECURSION_LIMIT = 25
REACT_MAX_HITL_CYCLES = REACT_RECURSION_LIMIT // 2

_TOOL_USE_FAILED = "tool_use_failed"
_MAX_TOOL_RETRIES = 5
_RETRY_DELAY = 0.5
_AINVOKE_TIMEOUT = 120  # cap waits so stuck LLM/tool calls cannot block forever


def _langchain_react_middleware(agent: dict, *extra: Any) -> list[Any]:
    """Middleware for LangChain ``create_agent`` inside ReAct (tool_choice + optional HITL)."""
    chain: list[Any] = []
    if agent.get("react_force_tool_choice_on_user_turn", True):
        chain.append(ReactUserTurnToolChoiceMiddleware())
    chain.extend(extra)
    return chain


def _exception_indicates_tool_use_failed(exc: BaseException) -> bool:
    """True when the provider rejected the model turn as invalid tool output (e.g. Groq ``tool_use_failed``)."""
    visited: set[int] = set()

    def _walk(err: BaseException | None) -> bool:
        if err is None:
            return False
        eid = id(err)
        if eid in visited:
            return False
        visited.add(eid)
        low = str(err).lower()
        if "tool_use_failed" in low or "failed_generation" in low:
            return True
        body = getattr(err, "body", None)
        if isinstance(body, dict):
            nested = body.get("error")
            if isinstance(nested, dict):
                if nested.get("code") == _TOOL_USE_FAILED:
                    return True
                if _TOOL_USE_FAILED in str(nested.get("message", "")).lower():
                    return True
        resp = getattr(err, "response", None)
        if resp is not None:
            json_fn = getattr(resp, "json", None)
            if callable(json_fn):
                try:
                    payload = json_fn()
                    if isinstance(payload, dict):
                        nested = payload.get("error")
                        if isinstance(nested, dict) and nested.get("code") == _TOOL_USE_FAILED:
                            return True
                except Exception:
                    pass
        cause = err.__cause__
        if cause is not None and _walk(cause):
            return True
        ctx = err.__context__
        if ctx is not None and ctx is not cause and _walk(ctx):
            return True
        return False

    return _walk(exc)


def _extract_failed_generation_snippet(exc: BaseException, *, max_len: int = 320) -> str:
    """Best-effort parse of provider ``failed_generation`` text for retry hints."""
    visited: set[int] = set()

    def from_dict(d: dict) -> str:
        err = d.get("error")
        if isinstance(err, dict):
            fg = err.get("failed_generation")
            if isinstance(fg, str) and fg.strip():
                return fg.strip()[:max_len]
        return ""

    def _walk(err: BaseException | None) -> str:
        if err is None:
            return ""
        eid = id(err)
        if eid in visited:
            return ""
        visited.add(eid)
        body = getattr(err, "body", None)
        if isinstance(body, dict):
            hit = from_dict(body)
            if hit:
                return hit
        resp = getattr(err, "response", None)
        if resp is not None:
            json_fn = getattr(resp, "json", None)
            if callable(json_fn):
                try:
                    payload = json_fn()
                    if isinstance(payload, dict):
                        hit = from_dict(payload)
                        if hit:
                            return hit
                except Exception:
                    pass
        hit = _walk(err.__cause__ or None)
        if hit:
            return hit
        ctx = err.__context__
        if ctx is not None and ctx is not err.__cause__:
            return _walk(ctx)
        return ""

    return _walk(exc)


def _human_message_after_tool_use_failed(exc: BaseException) -> str:
    """User/system message to nudge the model after a ``tool_use_failed`` response."""
    snippet = _extract_failed_generation_snippet(exc)
    parts = [
        "The API rejected your last assistant turn: it was not a valid structured **tool call**.",
        "Do **not** output plain text that claims a tool already ran (e.g. \"The file was read successfully\"). "
        "That triggers tool_use_failed on Groq.",
        "Invoke the needed tool via tool-calling only (e.g. read_file with a valid path). "
        "Wait for the tool result message, then reply with the file content or summary.",
    ]
    if snippet:
        parts.insert(
            1,
            f"Invalid style the API rejected (do not repeat): {snippet!r}",
        )
    return "\n".join(parts)


REACT_TOOL_DISCIPLINE = """

=== TOOL USAGE RULES ===
- Call each tool ONCE per task — do not repeat the same tool call.
- After receiving a tool result, synthesize and respond IMMEDIATELY.
- Do NOT call more tools unless the result explicitly requires it.
- Return your final answer right after getting the tool output.
- **Tool-calling turns (Groq / OpenAI-style)**: When you need a tool, emit **only** valid structured tool calls for that turn.
  Do not mix free-form assistant prose that *describes* tool outcomes before the tool runs — that is rejected as ``tool_use_failed``.

=== FINAL ANSWER — CODING-AGENT CLI ===
- Never claim tool results (e.g. file contents) until the tool has returned — Groq will reject prose masquerading as a tool call.
- Behave like Cursor / Claude Code in the terminal: **outcome-first**, not a tutorial.
- If tools already did the work (e.g. write_file, run_shell), the UI shows tool traces. Your **final** message must be **short**: what you did, file paths or command outcomes, errors if any, one optional next step. **Do not** write "Step 1 / Step 2" walkthroughs or explain *how* to do something you already finished with tools.
- Do not repeat long tool arguments, JSON payloads, or full file bodies unless the user explicitly asked to review them.
- Default length: a few sentences or a tiny bullet list. Go longer only when the user asks for depth, design, or teaching.
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
    ml = agent.get("max_step_output_length", 0)

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
                input=query,
                output=resp.content,
                duration_ms=dur,
                max_length=ml,
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
            messages=[
                SystemMessage(content=agent["system_prompt"]),
                HumanMessage(content=query),
                resp,
            ],
        )

    if hitl_active:
        return await _handle_react_hitl(
            agent=agent,
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
        middleware=_langchain_react_middleware(agent),
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
            _collect_tool_steps(response, steps, max_length=ml)
            steps.append(
                _make_step(
                    StepType.LLM_CALL,
                    "react_agent",
                    input=query,
                    output=output,
                    duration_ms=dur,
                    max_length=ml,
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
                messages=response.get("messages", []),
            )

        except GraphRecursionError:
            logger.warning(f"[React] ⚠ Recursion limit ({REACT_RECURSION_LIMIT}) reached.")
            partial = "Step limit reached — partial result may be incomplete."
            try:
                partial = _extract_last_ai_message(response) or partial
            except Exception:
                pass
            steps.append(_make_step(StepType.FALLBACK, "react_recursion_limit", output=partial, max_length=ml))
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=partial,
                steps_taken=REACT_RECURSION_LIMIT,
                success=True,
                analysis=analysis,
                steps=steps,
                messages=(response or {}).get("messages", []),
            )

        except Exception as exc:
            if _exception_indicates_tool_use_failed(exc) and attempt < _MAX_TOOL_RETRIES:
                logger.warning(
                    f"[React] ⚠ tool_use_failed on attempt "
                    f"{attempt}/{_MAX_TOOL_RETRIES} (agent={name}) "
                    f"— retrying in {_RETRY_DELAY}s."
                )
                await asyncio.sleep(_RETRY_DELAY)
                state = {
                    "messages": state["messages"]
                    + [HumanMessage(content=_human_message_after_tool_use_failed(exc))]
                }
                continue

            logger.error(f"[React] ❌ Failed: {exc}")
            fail_note = (
                "Provider rejected the model's tool output (tool_use_failed — usually prose instead of a structured tool call). "
                if _exception_indicates_tool_use_failed(exc)
                else ""
            )
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=f"{fail_note}REACT execution failed: {exc}",
                steps_taken=attempt,
                success=False,
                analysis=analysis,
                steps=steps,
                messages=(response or {}).get("messages", []),
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
    ml = agent.get("max_step_output_length", 0)

    react_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=_langchain_react_middleware(agent),
    )

    invoke_config = cast(
        RunnableConfig,  # noqa: TC006
        {**(config or {}), "recursion_limit": REACT_RECURSION_LIMIT},
    )
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
                                "input": _trunc(str(tool_input), ml),
                            },
                        )
                    )
                steps.append(
                    _make_step(
                        StepType.TOOL_CALL,
                        tool_name,
                        input=str(tool_input),
                        id=run_id,
                        max_length=ml,
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
                                "output": _trunc(tool_output, ml),
                            },
                        )
                    )
                steps.append(
                    _make_step(
                        StepType.TOOL_RESULT,
                        tool_name,
                        output=tool_output,
                        id=run_id,
                        max_length=ml,
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
                input=query,
                output=output,
                duration_ms=dur,
                max_length=ml,
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
            messages=(final_response or {}).get("messages", []),
        )

    except GraphRecursionError:
        logger.warning(f"[React|stream] Recursion limit ({REACT_RECURSION_LIMIT}) reached.")
        partial = "Step limit reached — partial result may be incomplete."
        try:
            partial = _extract_last_ai_message(final_response) or partial
        except Exception:
            pass
        steps.append(_make_step(StepType.FALLBACK, "react_recursion_limit", output=partial, max_length=ml))
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=partial,
            steps_taken=REACT_RECURSION_LIMIT,
            success=True,
            analysis=analysis,
            steps=steps,
            messages=(final_response or {}).get("messages", []),
        )

    except Exception as exc:
        logger.warning(
            f"[React|stream] astream_events failed ({type(exc).__name__}: {exc}) — falling back to ainvoke for {name}"
        )
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
    """Fallback to standard ainvoke when streaming is unavailable.

    Emits tool_call/tool_result events post-hoc to the event queue so
    UI consumers still receive tool visibility even on the fallback path.
    """
    llm = agent["llm"]
    tools = agent["tools"]
    system_prompt = agent["system_prompt"] + REACT_TOOL_DISCIPLINE
    steps: list = (config or {}).get("_steps", [])
    event_queue = agent.get("_event_queue")
    ml = agent.get("max_step_output_length", 0)

    react_agent = create_agent(model=llm, tools=tools, system_prompt=system_prompt)
    invoke_config = cast(
        RunnableConfig,  # noqa: TC006
        {**(config or {}), "recursion_limit": REACT_RECURSION_LIMIT},
    )
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

        tool_steps_start = len(steps)
        _collect_tool_steps(response, steps, max_length=ml)

        if event_queue:
            for step in steps[tool_steps_start:]:
                if step.type in (StepType.TOOL_CALL, StepType.TOOL_RESULT):
                    event_type = "tool_call" if step.type == StepType.TOOL_CALL else "tool_result"
                    await event_queue.put(
                        AgentEvent(
                            type=event_type,
                            data={
                                "name": step.name,
                                "input": step.input,
                                "output": step.output,
                                **step.metadata,
                            },
                        )
                    )

        steps.append(
            _make_step(
                StepType.LLM_CALL,
                "react_agent",
                input=query,
                output=output,
                duration_ms=dur,
                max_length=ml,
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
            messages=response.get("messages", []),
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
    agent: dict,
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
        middleware=_langchain_react_middleware(agent, approval_middleware),
    )

    invoke_config = {
        **(incoming_config or {}),
        "recursion_limit": REACT_RECURSION_LIMIT,
    }
    response: dict | None = None
    messages: list = [HumanMessage(content=query)]

    for attempt in range(1, _MAX_TOOL_RETRIES + 1):
        try:
            response = await asyncio.wait_for(
                react_agent.ainvoke(  # type: ignore[no-matching-overload]
                    {"messages": messages},
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
                messages=(response or {}).get("messages", []),
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
                messages=(response or {}).get("messages", []),
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
                messages=(response or {}).get("messages", []),
            )

        except Exception as exc:
            if _exception_indicates_tool_use_failed(exc) and attempt < _MAX_TOOL_RETRIES:
                logger.warning(
                    f"[React|HITL] ⚠ tool_use_failed on attempt "
                    f"{attempt}/{_MAX_TOOL_RETRIES} (agent={name}) "
                    f"— retrying in {_RETRY_DELAY}s."
                )
                await asyncio.sleep(_RETRY_DELAY)
                messages.append(HumanMessage(content=_human_message_after_tool_use_failed(exc)))
                response = None
                continue

            logger.error(f"[React|HITL] ❌ Failed: {exc}")
            fail_note = (
                "Provider tool_use_failed (model used prose instead of a structured tool call) — not a human-approval block. "
                if _exception_indicates_tool_use_failed(exc)
                else ""
            )
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=f"{fail_note}REACT HITL execution failed: {exc}",
                steps_taken=attempt,
                success=False,
                analysis=analysis,
                messages=(response or {}).get("messages", []),
            )

    return ExecutionResult(
        pattern_used=PatternType.REACT,
        query=query,
        output="REACT HITL exhausted tool-call retries.",
        steps_taken=_MAX_TOOL_RETRIES,
        success=False,
        analysis=analysis,
        messages=(response or {}).get("messages", []),
    )


def _collect_tool_steps(response: dict | None, steps: list, *, max_length: int = 0) -> None:
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


def _extract_last_ai_message(response: dict | None) -> str:
    """Walk messages in reverse — return first AIMessage with content and no pending tool_calls."""
    if not isinstance(response, dict):
        return ""
    for msg in reversed(response.get("messages", [])):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            content = msg.content
            return content if isinstance(content, str) else str(content)
    return ""
