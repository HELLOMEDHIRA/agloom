"""ReAct pattern — single agent + tool-calling loop with optional L2 HITL."""

import asyncio
import time
from typing import Any, cast

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from ..hitl_contract import (
    DEFAULT_REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL,
    DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS,
    REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL_KEY,
    REACT_TOOL_USE_FAILED_USER_ROUNDS_KEY,
    HITLEvent,
    call_user_callback,
    normalize_react_tool_use_failed_decision,
)
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
from .react_tool_recovery import (
    exception_indicates_tool_use_failed as _exception_indicates_tool_use_failed,
)
from .react_tool_recovery import (
    extract_failed_generation_snippet as _extract_failed_generation_snippet,  # re-export for tests / consumers # noqa: F401
)
from .react_tool_recovery import (
    human_message_after_stray_tool_json as _human_message_after_stray_tool_json,
)
from .react_tool_recovery import (
    human_message_after_tool_use_failed as _human_message_after_tool_use_failed,
)
from .react_tool_recovery import (
    last_ai_message_is_stray_tool_json as _last_ai_message_is_stray_tool_json,
)

logger = get_logger(__name__)


REACT_RECURSION_LIMIT = 25
REACT_MAX_HITL_CYCLES = REACT_RECURSION_LIMIT // 2

_MAX_TOOL_RETRIES = 5
_RETRY_DELAY = 0.5
# Cap ``ainvoke`` when **L2 HITL is off** — stuck model/tool loops cannot block forever.
# The HITL path must not use this: ``ainvoke`` then includes time inside ``user_callback``
# (approve/reject), which may take arbitrarily long.
_AINVOKE_TIMEOUT = 120
_STRAY_TOOL_JSON_RETRIES = 3


def _react_tool_names(tools: list[Any]) -> frozenset[str]:
    return frozenset(
        n.strip()
        for t in tools
        for n in (getattr(t, "name", None),)
        if isinstance(n, str) and n.strip()
    )


def _langchain_react_middleware(agent: dict, *extra: Any) -> list[Any]:
    """Middleware for LangChain ``create_agent`` inside ReAct (tool_choice + optional HITL)."""
    chain: list[Any] = []
    if agent.get("react_force_tool_choice_on_user_turn", True):
        chain.append(ReactUserTurnToolChoiceMiddleware())
    chain.extend(extra)
    return chain


def _hitl_middleware_extras(agent: dict) -> list[Any]:
    """L2 HumanApprovalMiddleware instances when ``interrupt_before_tools`` + ``user_callback`` are set."""
    interrupt_before_tools = agent.get("interrupt_before_tools") or []
    user_callback = agent.get("user_callback")
    if not interrupt_before_tools or not user_callback:
        return []
    return [
        HumanApprovalMiddleware(
            interrupt_before_tools=list(interrupt_before_tools),
            user_callback=user_callback,
            agent_name=agent.get("name", "UnifiedAgent"),
        )
    ]


async def _user_decision_after_tool_use_failed(user_callback: Any, exc: BaseException) -> str:
    """Ask human whether to attempt another model turn after provider rejection (not tool approval)."""
    if not user_callback:
        return "abort"
    try:
        raw = await call_user_callback(user_callback, HITLEvent.REACT_TOOL_USE_FAILED, str(exc))
    except Exception as e:
        logger.warning(f"[React] {HITLEvent.REACT_TOOL_USE_FAILED} callback raised {e!r} — aborting.")
        return "abort"
    return normalize_react_tool_use_failed_decision(raw)


REACT_TOOL_DISCIPLINE = """

=== TOOL USAGE RULES ===
- Do **not** repeat the **same** tool call with identical arguments. Multiple calls are required when
  inputs differ (e.g. **read_file** with advancing ``offset`` / ``limit`` to page through a large file,
  or another path after a failed lookup).
- Prefer **small, purposeful reads**: use ``read_file`` with ``limit`` (and increase ``offset`` using
  the continuation hint in the tool result) instead of pulling huge ranges in one call. Use
  **grep_files** when searching for a symbol or pattern across a file or tree.
- Tool truthfulness contract: if you claim you **read/fetched/ran** something via a tool, you must
  include the relevant excerpt in your final answer **or** explicitly mark it as incomplete and
  continue. Never imply you saw data you did not receive.
- UI-agnostic: never say “shown above / below” — the user only sees what you print in the Answer.
- Completeness: if a tool returns an ``[agloom:tool_result]`` envelope with ``complete=false``, treat
  the payload as **partial** (usually with a preview). Follow Recovery hints and paginate/narrow the
  request; do not summarize as if complete.
- After a tool returns, either call the **next** tool your plan needs or give the **final** answer —
  do not idle in a loop with redundant identical calls.
- **Tool-calling turns (Groq / OpenAI-style)**: When you need a tool, emit **only** valid structured tool calls for that turn.
  Do not mix free-form assistant prose that *describes* tool outcomes before the tool runs — that is rejected as ``tool_use_failed``.
- **Never** print JSON objects that look like ``{"name": "...", "parameters": ...}`` as assistant text — that bypasses the tool runner; use native tool calls only.

=== FINAL ANSWER — CODING-AGENT CLI ===
- Never claim tool results (e.g. file contents) until the tool has returned — Groq will reject prose masquerading as a tool call.
- **Final user-visible text = normal prose only.** Do not lead with pseudo-invocations: no ``left-hand-side -> outcome`` lines where the left side is structured arguments or JSON-like blobs, and no pasting of tool message shapes the runtime would emit. Summarize in sentences; the UI already shows real tool traces.
- Behave like Cursor / Claude Code in the terminal: **outcome-first**, not a tutorial.
- If tools already did the work, the UI shows tool traces. Your **final** message must be **short**: what you did, paths or command outcomes, errors if any, one optional next step. **Do not** write "Step 1 / Step 2" walkthroughs or explain *how* to do something you already finished with tools.
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
        messages = [
            SystemMessage(content=agent["system_prompt"]),
            HumanMessage(content=query),
        ]
        event_queue = agent.get("_event_queue")
        if event_queue is not None:
            eq = event_queue
            _timeout = float(agent.get("llm_timeout", 120.0))
            chunks: list[str] = []
            last_chunk = None

            async def _stream_no_tools() -> None:
                nonlocal last_chunk
                async for chunk in llm.astream(messages):
                    last_chunk = chunk
                    content = getattr(chunk, "content", "")
                    if content:
                        content = content if isinstance(content, str) else str(content)
                        chunks.append(content)
                        await eq.put(AgentEvent(type="token", data={"content": content}))

            await asyncio.wait_for(_stream_no_tools(), timeout=_timeout)
            output = "".join(chunks) or "No output produced."
            usage = _extract_token_usage(last_chunk) if last_chunk else {}
            out_messages: list = messages + ([last_chunk] if last_chunk else [])
        else:
            resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=_AINVOKE_TIMEOUT)
            output = resp.content if isinstance(resp.content, str) else str(resp.content)
            usage = _extract_token_usage(resp)
            out_messages = messages + [resp]
        dur = round((time.perf_counter() - t0) * 1000, 1)
        steps.append(
            _make_step(
                StepType.LLM_CALL,
                "react_fallback_llm",
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
            steps_taken=1,
            success=True,
            analysis=analysis,
            steps=steps,
            token_usage=usage,
            messages=out_messages,
        )

    event_queue = agent.get("_event_queue")
    if event_queue is not None:
        # CLI / UIs: always drive ReAct with ``astream_events`` so tokens and tool traces are live.
        # L2 HITL is layered via middleware on the same streaming agent (no ``ainvoke`` hot path).
        return await _handle_react_streaming(
            agent=agent,
            query=query,
            analysis=analysis,
            config=config,
            event_queue=event_queue,
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
    user_cb = agent.get("user_callback")
    attempt = 0
    max_attempts = _MAX_TOOL_RETRIES
    tool_names = _react_tool_names(tools)
    stray_remaining = _STRAY_TOOL_JSON_RETRIES
    try:
        user_recovery_budget = int(
            agent.get(REACT_TOOL_USE_FAILED_USER_ROUNDS_KEY, DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS)
        )
    except (TypeError, ValueError):
        user_recovery_budget = DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS

    while attempt < max_attempts:
        attempt += 1
        try:
            t0 = time.perf_counter()
            response = await asyncio.wait_for(
                react_agent.ainvoke(state, config=invoke_config),  # type: ignore[arg-type]
                timeout=_AINVOKE_TIMEOUT,
            )
            dur = round((time.perf_counter() - t0) * 1000, 1)

            msgs = response.get("messages", [])
            if (
                stray_remaining > 0
                and tool_names
                and _last_ai_message_is_stray_tool_json(msgs, tool_names)
            ):
                stray_remaining -= 1
                logger.warning(
                    f"[React] Model returned tool intent as plain JSON text (not structured tool_calls) "
                    f"— nudging provider; retries left={stray_remaining} (agent={name})."
                )
                await asyncio.sleep(_RETRY_DELAY)
                state = {
                    "messages": list(msgs) + [HumanMessage(content=_human_message_after_stray_tool_json())]
                }
                continue

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
            if _exception_indicates_tool_use_failed(exc):
                if attempt < max_attempts:
                    logger.warning(
                        f"[React] ⚠ tool_use_failed on attempt "
                        f"{attempt}/{max_attempts} (agent={name}) "
                        f"— retrying in {_RETRY_DELAY}s."
                    )
                    await asyncio.sleep(_RETRY_DELAY)
                    state = {
                        "messages": state["messages"]
                        + [HumanMessage(content=_human_message_after_tool_use_failed(exc))]
                    }
                    continue
                if user_cb and user_recovery_budget > 0:
                    user_recovery_budget -= 1
                    decision = await _user_decision_after_tool_use_failed(user_cb, exc)
                    if decision == "retry":
                        max_attempts += _MAX_TOOL_RETRIES
                        logger.event(
                            f"[React] User authorized another model-turn batch after "
                            f"REACT_TOOL_USE_FAILED (recovery rounds left={user_recovery_budget})."
                        )
                        await asyncio.sleep(_RETRY_DELAY)
                        state = {
                            "messages": state["messages"]
                            + [HumanMessage(content=_human_message_after_tool_use_failed(exc))]
                        }
                        continue

            logger.error(f"[React] ❌ Failed: {exc!r}")
            fail_note = (
                "Provider rejected the model's tool output (tool_use_failed — usually prose instead of a structured tool call). "
                if _exception_indicates_tool_use_failed(exc)
                else ""
            )
            exc_str = str(exc).strip() or repr(exc)
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=f"{fail_note}REACT execution failed: {exc_str}",
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
        steps_taken=max_attempts,
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

    hitl_extras = _hitl_middleware_extras(agent)
    hitl_active = bool(hitl_extras)

    react_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=_langchain_react_middleware(agent, *hitl_extras),
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
        tool_names = _react_tool_names(tools)
        output = _extract_last_ai_message(final_response)
        if not output:
            output = "No output produced."

        msgs = (final_response or {}).get("messages", [])
        if tool_names and _last_ai_message_is_stray_tool_json(msgs, tool_names):
            logger.warning(f"[React|stream] Stray tool JSON — one follow-up ainvoke (agent={name}).")
            recovery_state = {
                "messages": list(msgs) + [HumanMessage(content=_human_message_after_stray_tool_json())]
            }
            if hitl_active:
                final_response = await react_agent.ainvoke(recovery_state, config=invoke_config)  # type: ignore[arg-type]
            else:
                final_response = await asyncio.wait_for(
                    react_agent.ainvoke(recovery_state, config=invoke_config),  # type: ignore[arg-type]
                    timeout=_AINVOKE_TIMEOUT,
                )
            output = _extract_last_ai_message(final_response) or output
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


async def _emit_react_tool_steps_to_event_queue(agent: dict, tool_steps: list) -> None:
    """Emit tool_call / tool_result events for ``ainvoke`` paths (non-streaming HITL, stream fallback).

    Streaming ReAct + HITL uses ``astream_events`` directly; this backfills the queue when we fall
    back to ``ainvoke`` or use :func:`_handle_react_hitl`.
    """
    queue = agent.get("_event_queue")
    if not queue:
        return
    for step in tool_steps:
        if step.type not in (StepType.TOOL_CALL, StepType.TOOL_RESULT):
            continue
        event_type = "tool_call" if step.type == StepType.TOOL_CALL else "tool_result"
        await queue.put(
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
    ml = agent.get("max_step_output_length", 0)

    hitl_extras = _hitl_middleware_extras(agent)
    hitl_active = bool(hitl_extras)

    react_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=_langchain_react_middleware(agent, *hitl_extras),
    )
    invoke_config = cast(
        RunnableConfig,  # noqa: TC006
        {**(config or {}), "recursion_limit": REACT_RECURSION_LIMIT},
    )
    state = {"messages": [{"role": "user", "content": query}]}

    try:
        t0 = time.perf_counter()
        if hitl_active:
            response = await react_agent.ainvoke(state, config=invoke_config)
        else:
            response = await asyncio.wait_for(
                react_agent.ainvoke(state, config=invoke_config),
                timeout=_AINVOKE_TIMEOUT,
            )
        dur = round((time.perf_counter() - t0) * 1000, 1)
        output = _extract_last_ai_message(response) or "No output produced."
        usage = _extract_token_usage(response)

        tool_steps_start = len(steps)
        _collect_tool_steps(response, steps, max_length=ml)
        await _emit_react_tool_steps_to_event_queue(agent, steps[tool_steps_start:])

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
        logger.error(f"[React|fallback] Failed: {exc!r}")
        exc_str = str(exc).strip() or repr(exc)
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=f"REACT execution failed: {exc_str}",
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
    """L2 HITL via ``ainvoke`` when no ``_event_queue`` (library / non-streaming callers).

    The CLI always sets ``_event_queue`` and uses :func:`_handle_react_streaming` with the same
    middleware so the UI stays on ``astream_events``.
    """
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
    user_cb = user_callback
    attempt = 0
    silent_in_batch = 0
    try:
        user_recovery_budget = int(
            agent.get(REACT_TOOL_USE_FAILED_USER_ROUNDS_KEY, DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS)
        )
    except (TypeError, ValueError):
        user_recovery_budget = DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS
    try:
        hitl_auto_retries = int(
            agent.get(
                REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL_KEY,
                DEFAULT_REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL,
            )
        )
    except (TypeError, ValueError):
        hitl_auto_retries = DEFAULT_REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL
    hitl_auto_retries = max(0, min(hitl_auto_retries, _MAX_TOOL_RETRIES))
    # Each batch: up to hitl_auto_retries silent model-turn recoveries, then optional user prompt.
    batch_size = hitl_auto_retries + 1
    max_attempts = batch_size
    tool_names = _react_tool_names(tools)
    stray_remaining = _STRAY_TOOL_JSON_RETRIES

    while attempt < max_attempts:
        attempt += 1
        silent_in_batch += 1
        try:
            # No outer timeout: HumanApprovalMiddleware may await the CLI/TUI until the user
            # decides — asyncio.wait_for would raise TimeoutError during an open prompt.
            response = await react_agent.ainvoke(  # type: ignore[no-matching-overload]
                {"messages": messages},
                config=invoke_config,
            )
            msgs = (response or {}).get("messages", [])
            if (
                stray_remaining > 0
                and tool_names
                and _last_ai_message_is_stray_tool_json(msgs, tool_names)
            ):
                stray_remaining -= 1
                logger.warning(
                    f"[React|HITL] Stray tool JSON in assistant text — nudging provider; "
                    f"retries left={stray_remaining} (agent={name})."
                )
                await asyncio.sleep(_RETRY_DELAY)
                messages = list(msgs) + [HumanMessage(content=_human_message_after_stray_tool_json())]
                continue

            ml = agent.get("max_step_output_length", 0)
            hitl_tool_steps: list = []
            _collect_tool_steps(response, hitl_tool_steps, max_length=ml)
            await _emit_react_tool_steps_to_event_queue(agent, hitl_tool_steps)

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
            logger.event("[React|HITL] ✋ Aborted by user (tool not run).")
            msgs: list[Any] = []
            if response is not None:
                try:
                    msgs = list((response or {}).get("messages", []))
                except Exception:
                    msgs = []
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output="Aborted",
                steps_taken=1,
                success=True,  # deliberate user action, not a failure
                analysis=analysis,
                metadata={"user_aborted_tool": True},
                messages=msgs,
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
            if _exception_indicates_tool_use_failed(exc):
                # Silent steps = corrective HumanMessage + new LLM call (no tool to approve yet).
                # Counter resets after user authorizes another batch.
                if silent_in_batch <= hitl_auto_retries:
                    if silent_in_batch < hitl_auto_retries:
                        logger.warning(
                            f"[React|HITL] ⚠ tool_use_failed — automatic model-turn recovery "
                            f"{silent_in_batch}/{hitl_auto_retries} (agent={name}); "
                            f"not tool approve/deny. Sleep {_RETRY_DELAY}s."
                        )
                    else:
                        logger.warning(
                            f"[React|HITL] ⚠ tool_use_failed — automatic recovery budget used "
                            f"({hitl_auto_retries}/{hitl_auto_retries}) for this batch "
                            f"(agent={name}); next failure invokes "
                            f"user_callback({HITLEvent.REACT_TOOL_USE_FAILED!r}, …). "
                            f"Sleep {_RETRY_DELAY}s."
                        )
                    await asyncio.sleep(_RETRY_DELAY)
                    messages.append(HumanMessage(content=_human_message_after_tool_use_failed(exc)))
                    response = None
                    continue
                if user_cb and user_recovery_budget > 0:
                    user_recovery_budget -= 1
                    decision = await _user_decision_after_tool_use_failed(user_cb, exc)
                    if decision == "retry":
                        max_attempts += batch_size
                        silent_in_batch = 0
                        logger.event(
                            f"[React|HITL] User authorized another model-turn batch after "
                            f"REACT_TOOL_USE_FAILED (recovery rounds left={user_recovery_budget})."
                        )
                        await asyncio.sleep(_RETRY_DELAY)
                        messages.append(HumanMessage(content=_human_message_after_tool_use_failed(exc)))
                        response = None
                        continue

            logger.error(f"[React|HITL] ❌ Failed: {exc!r}")
            fail_note = (
                "Provider tool_use_failed (model used prose instead of a structured tool call) — not a human-approval block. "
                if _exception_indicates_tool_use_failed(exc)
                else ""
            )
            # Use ``repr(exc)`` so empty-message exceptions still surface their class name —
            # otherwise users see an unhelpful ``execution failed: `` with no diagnostic.
            exc_str = str(exc).strip() or repr(exc)
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=f"{fail_note}REACT HITL execution failed: {exc_str}",
                steps_taken=attempt,
                success=False,
                analysis=analysis,
                messages=(response or {}).get("messages", []),
            )

    return ExecutionResult(
        pattern_used=PatternType.REACT,
        query=query,
        output="REACT HITL exhausted tool-call retries.",
        steps_taken=max_attempts,
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
