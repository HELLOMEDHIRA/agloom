"""ReAct pattern — single agent + tool-calling loop with optional L2 HITL."""

import asyncio
import json
import time
from collections.abc import Mapping
from typing import Any, cast
from uuid import uuid4

from ..llm.chat_template_compat import (
    _DEFAULT_USER_TURN,
    ensure_messages_for_chat_template,
    exception_indicates_missing_user_query,
    extract_model_label,
    human_message_after_missing_user_query,
    uses_strict_chat_template,
    repair_react_graph_state,
)
from ..context.compaction import append_context_compaction_recap, compact_messages_for_budget
from ..context.tool_scratchpad import ToolScratchpad
from ..context.tokens import estimate_messages_tokens
from ..context.window import infer_context_window_tokens, reserved_output_tokens
from ..src.multimodal import content_blocks_to_text, text_from_user_turn
from ..src.wire_stream_content import (
    answer_text_from_content,
    emit_llm_chunk_to_event_queue,
    split_stream_parts_from_chunk,
)

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from ..src.hitl_contract import (
    DEFAULT_REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL,
    DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS,
    REACT_TOOL_USE_FAILED_AUTO_RETRIES_HITL_KEY,
    REACT_TOOL_USE_FAILED_USER_ROUNDS_KEY,
    HITLEvent,
    call_user_callback,
    normalize_react_tool_use_failed_decision,
)
from ..src.logging_utils import get_logger
from ..src.reserved_tools import TOOL_LOAD_SKILL, TOOL_RECALL_TOOL_ARTIFACT
from ..src.worker import resolve_event_queue
from ..src.models import (
    DEFAULT_SYSTEM_PROMPT,
    AgentEvent,
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    SignalType,
    StepType,
    _extract_token_usage,
    _make_step,
    _trunc,
)
from ._failure import exec_failure_kwargs
from .hitl_tool_coalesce import build_default_hitl_coalescer
from ._steps_accounting import steps_taken_from_audit
from .middleware import HumanApprovalMiddleware, UserAbort, build_langchain_agent_middleware
from .react_tool_recovery import (
    exception_indicates_context_window_exceeded,
    exception_indicates_tool_use_failed as _exception_indicates_tool_use_failed,
)
from .react_tool_recovery import (
    extract_failed_generation_snippet as _extract_failed_generation_snippet,  # noqa: F401 — re-export
)
from .react_tool_recovery import (
    human_message_after_stray_tool_json as _human_message_after_stray_tool_json,
)
from .react_tool_recovery import (
    human_message_after_tool_use_failed as _human_message_after_tool_use_failed,
)
from .react_tool_recovery import (
    is_stray_tool_json_text as _is_stray_tool_json_text,
)
from .react_tool_recovery import (
    last_ai_message_is_stray_tool_json as _last_ai_message_is_stray_tool_json,
)
from ..src.exception_utils import exception_indicates_transient_transport_error, format_exception_message

logger = get_logger(__name__)


async def _react_failure(
    agent: dict,
    config: dict | None,
    query: str | list[Any],
    analysis: QueryAnalysis,
    *,
    output: str,
    steps_taken: int,
    steps: list,
    messages: list | None = None,
    kind: str = "execution",
    error: str | None = None,
) -> ExecutionResult:
    from ..orchestrator.hooks import maybe_recover_react_failure

    failed = ExecutionResult(
        pattern_used=PatternType.REACT,
        query=query,
        output=output,
        steps_taken=steps_taken,
        success=False,
        analysis=analysis,
        steps=steps,
        messages=messages or [],
        **exec_failure_kwargs(error or output, kind=kind),
    )
    return await maybe_recover_react_failure(agent, config, query, analysis, failed)


def _llm_label_from_agent(agent: dict) -> str | None:
    llm = agent.get("llm")
    if llm is None:
        return None
    for attr in ("model_name", "model", "model_id"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    cls = getattr(llm, "__class__", None)
    return cls.__name__ if cls is not None else None


def _llm_step_metadata(agent: dict, usage: dict[str, int], *, phase: str) -> dict[str, Any]:
    extra: dict[str, Any] = {"phase": phase}
    if usage:
        extra["usage"] = usage
    lbl = _llm_label_from_agent(agent)
    if lbl:
        extra["model"] = lbl
    return extra


async def _emit_llm_call_step(
    run_config: dict | None,
    event_queue: asyncio.Queue | None,
    step: Any,
) -> None:
    """Push one ``llm_call`` AgentEvent so the runtime bridge can emit ``metric.tokens``."""
    cfg = run_config or {}
    if event_queue is not None and "_event_queue" not in cfg:
        cfg = {**cfg, "_event_queue": event_queue}
    from ..src.wire_tokens import emit_llm_call_from_step

    await emit_llm_call_from_step(cfg, step)


def _tool_input_as_dict(tool_input: Any) -> dict[str, Any]:
    if isinstance(tool_input, dict):
        return tool_input
    if isinstance(tool_input, str):
        try:
            parsed = json.loads(tool_input)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


REACT_RECURSION_LIMIT = 25  # default; override via create_agent(react_recursion_limit=…)

_MAX_TOOL_RETRIES = 5
_MAX_TRANSPORT_RETRIES = 3
# Hard ceiling on total ``ainvoke`` attempts (including user-authorized extensions).
REACT_ABSOLUTE_MAX_AINVOKE_ATTEMPTS = 24
_RETRY_DELAY = 0.5


def _react_retry_delay(attempt: int) -> float:
    """Exponential backoff capped at 8s (``attempt`` is 1-based)."""
    return min(_RETRY_DELAY * (2 ** min(max(0, attempt - 1), 4)), 8.0)


# Cap ``ainvoke`` when **L2 HITL is off** — stuck model/tool loops cannot block forever.
# The HITL path must not use this: ``ainvoke`` then includes time inside ``user_callback``
# (approve/reject), which may take arbitrarily long.
_AINVOKE_TIMEOUT = 120
_STRAY_TOOL_JSON_RETRIES = 3


async def _acquire_transport_llm(agent: dict) -> None:
    tm = agent.get("_transport_manager")
    if tm is not None:
        await tm.acquire_llm_slot()


from .react_timeouts import (
    react_graph_wall_timeout as _react_graph_wall_timeout,
    react_llm_timeout as _react_llm_timeout,
    react_recursion_limit as _react_recursion_limit,
    react_recursion_limit_failure_message as _react_recursion_limit_failure_message,
    react_timeout_failure_message as _react_timeout_failure_message,
)


async def _react_emit_stream_error(
    event_queue: asyncio.Queue | None,
    *,
    message: str,
    error_class: str,
    stage: str = "react",
) -> None:
    if event_queue is None:
        return
    await event_queue.put(
        AgentEvent(
            type="error",
            data={
                "error": message,
                "error_class": error_class,
                "stage": stage,
                "severity": "fatal",
            },
        )
    )


async def _react_recursion_limit_failure(
    agent: dict,
    config: dict | None,
    query: str | list[Any],
    analysis: QueryAnalysis,
    *,
    path: str,
    steps: list,
    steps_taken: int | None = None,
    messages: list | None = None,
    event_queue: asyncio.Queue | None = None,
    max_length: int = 0,
) -> ExecutionResult:
    """Hard stop when LangGraph hits ``recursion_limit`` — same contract as timeouts."""
    limit = _react_recursion_limit(agent)
    taken = steps_taken if steps_taken is not None else limit
    msg = _react_recursion_limit_failure_message(limit=limit, path=path)
    logger.warning(f"{path} ⚠ Recursion limit ({limit}) reached.")
    steps.append(_make_step(StepType.FALLBACK, "react_recursion_limit", output=msg, max_length=max_length))
    queue = event_queue if event_queue is not None else resolve_event_queue(agent, config)
    await _react_emit_stream_error(
        queue,
        message=msg,
        error_class="GraphRecursionError",
    )
    return await _react_failure(
        agent,
        config,
        query,
        analysis,
        output=msg,
        steps_taken=taken,
        steps=steps,
        messages=messages or [],
    )


async def _react_return_timeout_failure(
    agent: dict,
    config: dict | None,
    query: str | list[Any],
    analysis: QueryAnalysis,
    *,
    wall_seconds: float,
    path: str,
    steps_taken: int,
    steps: list,
    messages: list | None = None,
    event_queue: asyncio.Queue | None = None,
) -> ExecutionResult:
    msg = _react_timeout_failure_message(agent, wall_seconds=wall_seconds, path=path)
    logger.error(f"{path} Timed out ({int(wall_seconds)}s)")
    queue = event_queue if event_queue is not None else resolve_event_queue(agent, config)
    await _react_emit_stream_error(queue, message=msg, error_class="TimeoutError")
    return await _react_failure(
        agent,
        config,
        query,
        analysis,
        output=msg,
        steps_taken=steps_taken,
        steps=steps,
        messages=messages or [],
        kind="timeout",
        error="TimeoutError",
    )


def _react_tool_names(tools: list[Any]) -> frozenset[str]:
    return frozenset(
        n.strip()
        for t in tools
        for n in (getattr(t, "name", None),)
        if isinstance(n, str) and n.strip()
    )


def _react_opening_messages(query: str | list[Any]) -> list[Any]:
    """Opening user turn with plain-string content for strict chat templates when possible."""
    if isinstance(query, str):
        text = query.strip()
    else:
        text = text_from_user_turn(query).strip()
    if not text:
        logger.warning("[React] Empty user query — using default opening turn for tool agent")
        text = _DEFAULT_USER_TURN
    return ensure_messages_for_chat_template([HumanMessage(content=text)])


def _react_invoke_state(
    agent: dict,
    query: str | list[Any],
    state: dict | None = None,
) -> dict:
    """Normalize LangGraph state before ``ainvoke`` (template-safe user turn)."""
    if state is None:
        return {"messages": _react_opening_messages(query)}
    msgs = list(state.get("messages") or [])
    repaired = repair_react_graph_state(msgs, query, state=state)
    return {**state, "messages": repaired}


def _compact_react_state_for_context_pressure(agent: dict, state: dict) -> dict | None:
    """Emergency compaction when the provider reports context window exhaustion."""
    pad = agent.get("_tool_scratchpad")
    if not isinstance(pad, ToolScratchpad):
        return None
    from ..context.tool_scratchpad import MAX_TOOL_WIRE_CHARS

    window = int(agent.get("context_window_tokens") or infer_context_window_tokens(agent.get("llm")))
    reserved = int(
        agent.get("context_reserved_output_tokens")
        or reserved_output_tokens(agent.get("llm"), context_window=window)
    )
    ratio = float(agent.get("context_compact_ratio", 0.82))
    budget = max(2048, int(window * ratio) - reserved)
    max_wire = int(agent.get("max_tool_wire_chars", MAX_TOOL_WIRE_CHARS))
    msgs = list(state.get("messages") or [])
    if not msgs:
        return None
    compacted = compact_messages_for_budget(
        msgs,
        pad,
        target_input_tokens=budget,
        max_wire_chars=max_wire,
    )
    compacted = append_context_compaction_recap(compacted, scratchpad=pad)
    if estimate_messages_tokens(compacted) >= estimate_messages_tokens(msgs):
        return None
    return {**state, "messages": compacted}


def _langchain_react_middleware(agent: dict, *extra: Any) -> list[Any]:
    """Middleware for LangChain ``create_agent`` inside ReAct (tool_choice + optional HITL)."""
    from .tool_context_middleware import (
        build_tool_context_middleware,
        tool_context_settings_from_mapping,
    )

    leading: list[Any] = []
    trailing: list[Any] = []
    settings = tool_context_settings_from_mapping(agent)
    if settings is not None:
        budget_mw, scratch_mw = build_tool_context_middleware(settings)
        leading.append(budget_mw)
        trailing.append(scratch_mw)

    return build_langchain_agent_middleware(
        force_tool_choice_on_user_turn=bool(agent.get("react_force_tool_choice_on_user_turn", True)),
        extras=[*leading, *extra, *trailing],
    )


def _hitl_middleware_extras(agent: dict) -> list[Any]:
    """L2 HumanApprovalMiddleware instances when ``interrupt_before_tools`` + ``user_callback`` are set."""
    interrupt_before_tools = agent.get("interrupt_before_tools") or []
    user_callback = agent.get("user_callback")
    if not interrupt_before_tools or not user_callback:
        return []
    coalescer = agent.get("_hitl_tool_coalescer")
    if coalescer is None:
        coalescer = build_default_hitl_coalescer()
        agent["_hitl_tool_coalescer"] = coalescer
    return [
        HumanApprovalMiddleware(
            interrupt_before_tools=list(interrupt_before_tools),
            user_callback=user_callback,
            agent_name=agent.get("name", "UnifiedAgent"),
            tool_allowlist=agent.get("_hitl_tool_allowlist"),
            hitl_coalescer=coalescer,
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
- Answer the **current** user message only. Do not read or summarize unrelated files (e.g.
  ``pyproject.toml``) when the user asked about a **different path**, an existence check, or another task.
- For "does this path exist?" / existence checks, use the matching path/existence tool for that path —
  not ``read_file`` on a default project file.
- Do **not** emit **two** ``read_file`` calls for the **same** ``path`` in one assistant turn unless
  the first result had ``complete=false`` and you are **paging** with a higher ``offset``. The
  runtime may suppress a redundant second HITL for overlapping byte reads — still avoid double
  calls; they waste tokens and confuse users.
- Do **not** repeat the **same** tool call with identical arguments (other tools). Multiple calls are
  required when inputs differ (e.g. **read_file** with advancing ``offset`` / ``limit`` to page
  through a large file, or another path after a failed lookup).
- Prefer **small, purposeful reads**: ``read_file`` parameter ``limit`` is **bytes**, not lines — a few
  hundred bytes is only a tiny prefix. When the user asks for the **first N lines**, pass
  ``line_cap=N`` and a byte ``limit`` large enough for those lines (e.g. ``200 * N`` as a rough
  budget). Increase ``offset`` using the continuation hint to page. Use **grep_files** when
  searching for a symbol or pattern across a file or tree.
- Tool truthfulness contract: if you claim you **read/fetched/ran** something via a tool, you must
  include the relevant excerpt in your final answer **or** explicitly mark it as incomplete and
  continue. Never imply you saw data you did not receive.
- **Never** tell the user to **call**, **invoke**, **run**, or **use** a tool by name (e.g. “you can
  call ``read_file`` …”). They cannot run tools — **only you** can. If the first read was too small,
  issue another **tool call yourself** in the same turn (larger ``limit`` and/or ``line_cap``) until
  you can answer; do not end by delegating a second read to the user.
- UI-agnostic: never say “shown above / below”, “in the trace”, “in the panel”, “as displayed in the
  UI”, or similar — the user only sees what you print in your **Answer** text. When they asked for
  file lines or content, **paste the excerpt** (or the requested line range) in that answer, not a
  pointer to elsewhere.
- Do **not** claim a line count (e.g. “first 8 lines”) unless the tool output you actually received
  contains at least that many **logical** lines for the path you read.
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
- If tools already did the work, the UI shows tool traces. Your **final** message must be **short**:
  what you did, paths or command outcomes, errors if any, one optional next step. **Do not** write
  "Step 1 / Step 2" walkthroughs or explain *how* to do something you already finished with tools.
- If the user asked for **concrete file content** (lines, snippet, “show me …”), your final message
  must include that content **in prose** (quoted or fenced) when it fits; do not substitute with
  “see above” or “call read_file again”.
- Do not repeat long tool arguments, JSON payloads, or full file bodies unless the user explicitly asked to review them.
- Do **not** meta-comment about the UI ("shown above", "not long enough to show N lines", "the file is displayed in the trace") — paste the excerpt or give a direct summary in your answer.
- Default length: a few sentences or a tiny bullet list. Go longer only when the user asks for depth, design, or teaching.
"""

MCP_TOOL_DISCIPLINE = f"""

=== MCP / EXTERNAL TOOL LIMITS (strict) ===
- When a tool schema exposes ``limit``, ``page_size``, ``max_results``, ``top_k``, ``per_page``, or similar pagination fields, you **must** pass a conservative value on the **first** call (start with ≤50–100 unless the user asked for more).
- Prefer **narrow** queries (time range, service name, log level, IDs) before broad “get everything” calls.
- If a tool returns ``[agloom:tool_digest …]`` or ``complete=false``, use ``{TOOL_RECALL_TOOL_ARTIFACT}(ref_id, offset, limit)`` to page — **never** repeat the same unbounded tool call with identical arguments.
- Large digests mean the full payload is off-thread; recall slices are the correct next step, not a duplicate MCP call.
"""


def _react_base_system_prompt(agent: dict) -> str:
    """Resolve a string system prompt (never ``None``) for ReAct."""
    base = agent.get("system_prompt")
    if isinstance(base, str) and base.strip():
        return base
    if base is not None and not isinstance(base, str):
        return str(base)
    return DEFAULT_SYSTEM_PROMPT


def _react_system_prompt(agent: dict) -> str:
    prompt = _react_base_system_prompt(agent) + REACT_TOOL_DISCIPLINE
    if agent.get("_mcp_servers"):
        prompt += MCP_TOOL_DISCIPLINE
    return prompt


async def handle_react(
    agent: dict,
    query: str | list[Any],
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
    system_prompt = _react_system_prompt(agent)
    name = agent.get("name", "UnifiedAgent")
    interrupt_before_tools = agent.get("interrupt_before_tools", [])
    user_callback = agent.get("user_callback")
    steps: list = (config or {}).get("_steps", [])
    ml = agent.get("max_step_output_length", 0)

    hitl_active = bool(interrupt_before_tools and user_callback)

    logger.event(f"[React] ▶ {name} — {len(tools)} tools available | HITL={'Level2-Tool' if hitl_active else 'off'}")

    try:
        from agloom import __version__ as _agloom_version
    except Exception:
        _agloom_version = "unknown"
    _llm = agent.get("llm")
    _mlabel = extract_model_label(_llm)
    logger.info(
        f"[React] agloom={_agloom_version} model_label={_mlabel!r} "
        f"strict_chat_template={uses_strict_chat_template(_mlabel)}"
    )

    if not tools:
        logger.debug("[React] No tools — direct LLM fallback.")
        t0 = time.perf_counter()
        messages = [
            SystemMessage(content=_react_base_system_prompt(agent)),
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
                    reasoning, answer = await emit_llm_chunk_to_event_queue(eq, chunk)
                    if answer:
                        chunks.append(answer)

            await asyncio.wait_for(_stream_no_tools(), timeout=_timeout)
            output = "".join(chunks) or "No output produced."
            usage = _extract_token_usage(last_chunk) if last_chunk else {}
            out_messages: list = messages + ([last_chunk] if last_chunk else [])
        else:
            resp = await asyncio.wait_for(llm.ainvoke(messages), timeout=_AINVOKE_TIMEOUT)
            output = answer_text_from_content(resp.content) or "No output produced."
            usage = _extract_token_usage(resp)
            out_messages = messages + [resp]
        dur = round((time.perf_counter() - t0) * 1000, 1)
        steps.append(
            _make_step(
                StepType.LLM_CALL,
                "react_fallback_llm",
                input=text_from_user_turn(query),
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

    return await _run_react_ainvoke_with_retries(
        agent=agent,
        query=query,
        analysis=analysis,
        config=config,
    )


async def _run_react_ainvoke_with_retries(
    agent: dict,
    query: str | list[Any],
    analysis: QueryAnalysis,
    config: dict | None = None,
    *,
    react_agent: Any | None = None,
    initial_state: dict | None = None,
    attempt_offset: int = 0,
    collect_tool_steps: bool = True,
    emit_tool_events_to_queue: bool = False,
    log_prefix: str = "[React]",
) -> ExecutionResult:
    """Shared ``ainvoke`` loop: tool_use_failed retries, stray JSON recovery, optional HITL extension."""
    llm = agent["llm"]
    tools = agent["tools"]
    system_prompt = _react_system_prompt(agent)
    name = agent.get("name", "UnifiedAgent")
    steps: list = (config or {}).get("_steps", [])
    ml = agent.get("max_step_output_length", 0)

    hitl_extras = _hitl_middleware_extras(agent)
    hitl_active = bool(hitl_extras)

    if react_agent is None:
        react_agent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=system_prompt,
            middleware=_langchain_react_middleware(agent, *hitl_extras),
        )

    invoke_config = cast(
        RunnableConfig,  # noqa: TC006
        {**(config or {}), "recursion_limit": _react_recursion_limit(agent)},
    )

    state = _react_invoke_state(agent, query, initial_state)
    response = None
    user_cb = agent.get("user_callback")
    attempt = max(0, attempt_offset)
    max_attempts = _MAX_TOOL_RETRIES
    tool_names = _react_tool_names(tools)
    stray_remaining = _STRAY_TOOL_JSON_RETRIES
    try:
        user_recovery_budget = int(
            agent.get(REACT_TOOL_USE_FAILED_USER_ROUNDS_KEY, DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS)
        )
    except (TypeError, ValueError):
        user_recovery_budget = DEFAULT_REACT_TOOL_USE_FAILED_USER_ROUNDS

    transport_retries = 0
    while attempt < max_attempts:
        attempt += 1
        if attempt > REACT_ABSOLUTE_MAX_AINVOKE_ATTEMPTS:
            logger.error(
                f"{log_prefix} Absolute ainvoke cap ({REACT_ABSOLUTE_MAX_AINVOKE_ATTEMPTS}) reached."
            )
            return await _react_failure(
                agent,
                config,
                query,
                analysis,
                output="REACT exceeded absolute attempt cap for tool/recovery retries.",
                steps_taken=attempt,
                steps=steps,
                messages=(response or {}).get("messages", []),
            )
        try:
            t0 = time.perf_counter()
            _wall_timeout = _react_llm_timeout(agent, config)
            await _acquire_transport_llm(agent)
            response = await asyncio.wait_for(
                cast(Any, react_agent).ainvoke(state, config=invoke_config),
                timeout=_wall_timeout,
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
                    f"{log_prefix} Model returned tool intent as plain JSON text (not structured tool_calls) "
                    f"— nudging provider; retries left={stray_remaining} (agent={name})."
                )
                await asyncio.sleep(_react_retry_delay(attempt))
                state = _react_invoke_state(
                    agent,
                    query,
                    {
                        "messages": list(msgs)
                        + [
                            HumanMessage(
                                content=_human_message_after_stray_tool_json(
                                    tool_result_already_present=any(
                                        isinstance(m, ToolMessage) for m in msgs
                                    )
                                )
                            )
                        ]
                    },
                )
                continue

            output = _extract_last_ai_message(response)
            if not output:
                output = "No output produced."

            usage = _extract_token_usage(response)
            if collect_tool_steps:
                tool_steps_start = len(steps)
                _collect_tool_steps(response, steps, max_length=ml)
                if emit_tool_events_to_queue:
                    await _emit_react_tool_steps_to_event_queue(agent, steps[tool_steps_start:])
            llm_step = _make_step(
                StepType.LLM_CALL,
                "react_agent",
                input=text_from_user_turn(query),
                output=output,
                duration_ms=dur,
                max_length=ml,
                messages=len(response.get("messages") or []),
                **_llm_step_metadata(agent, usage, phase="react_agent"),
            )
            steps.append(llm_step)
            queue = resolve_event_queue(agent, config)
            await _emit_llm_call_step(config, queue, llm_step)

            resp_messages = response.get("messages") or []
            logger.event(f"{log_prefix} ✅ Done — {len(resp_messages)} messages exchanged.")
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=output,
                steps_taken=steps_taken_from_audit(steps),
                success=True,
                analysis=analysis,
                steps=steps,
                token_usage=usage,
                messages=resp_messages,
            )

        except GraphRecursionError:
            return await _react_recursion_limit_failure(
                agent,
                config,
                query,
                analysis,
                path=log_prefix,
                steps=steps,
                messages=(response or {}).get("messages", []),
                max_length=ml,
            )

        except Exception as exc:
            from ..context.errors import ContextBudgetExceededError

            if isinstance(exc, ContextBudgetExceededError):
                return ExecutionResult(
                    pattern_used=PatternType.REACT,
                    query=query,
                    output=str(exc),
                    steps_taken=steps_taken_from_audit(steps),
                    success=False,
                    failure_class="context",
                    retryable=False,
                    analysis=analysis,
                    steps=steps,
                    messages=(response or {}).get("messages", []) if isinstance(response, dict) else [],
                    metadata={
                        "estimated_input_tokens": exc.estimated_tokens,
                        "budget": exc.budget,
                        "execution_path": f"{log_prefix}_context_budget",
                    },
                )
            if _exception_indicates_tool_use_failed(exc) or exception_indicates_missing_user_query(exc):
                if attempt < max_attempts:
                    nudge = (
                        _human_message_after_tool_use_failed(exc)
                        if _exception_indicates_tool_use_failed(exc)
                        else human_message_after_missing_user_query()
                    )
                    logger.warning(
                        f"{log_prefix} ⚠ model turn rejected on attempt "
                        f"{attempt}/{max_attempts} (agent={name}) "
                        f"— retrying in {_RETRY_DELAY}s: {format_exception_message(exc)}"
                    )
                    await asyncio.sleep(_react_retry_delay(attempt))
                    state = _react_invoke_state(
                        agent,
                        query,
                        {
                            "messages": state["messages"]
                            + [HumanMessage(content=nudge)]
                        },
                    )
                    continue
            elif exception_indicates_context_window_exceeded(exc) and attempt < max_attempts:
                compacted = _compact_react_state_for_context_pressure(agent, state)
                if compacted is not None:
                    logger.warning(
                        f"{log_prefix} ⚠ context window exceeded on attempt "
                        f"{attempt}/{max_attempts} (agent={name}) — compacting scratchpad "
                        f"and retrying: {format_exception_message(exc)}"
                    )
                    await asyncio.sleep(_react_retry_delay(attempt))
                    state = _react_invoke_state(agent, query, compacted)
                    continue
                if user_cb and user_recovery_budget > 0:
                    user_recovery_budget -= 1
                    decision = await _user_decision_after_tool_use_failed(user_cb, exc)
                    if decision == "retry":
                        max_attempts = min(
                            max_attempts + _MAX_TOOL_RETRIES,
                            REACT_ABSOLUTE_MAX_AINVOKE_ATTEMPTS,
                        )
                        if max_attempts <= attempt:
                            logger.error(
                                f"{log_prefix} User retry requested but absolute attempt cap "
                                f"({REACT_ABSOLUTE_MAX_AINVOKE_ATTEMPTS}) reached."
                            )
                            break
                        logger.event(
                            f"{log_prefix} User authorized another model-turn batch after "
                            f"REACT_TOOL_USE_FAILED (recovery rounds left={user_recovery_budget})."
                        )
                        await asyncio.sleep(_react_retry_delay(attempt))
                        nudge = (
                            _human_message_after_tool_use_failed(exc)
                            if _exception_indicates_tool_use_failed(exc)
                            else human_message_after_missing_user_query()
                        )
                        state = _react_invoke_state(
                            agent,
                            query,
                            {
                                "messages": state["messages"]
                                + [HumanMessage(content=nudge)]
                            },
                        )
                        continue
            elif (
                exception_indicates_transient_transport_error(exc)
                and transport_retries < _MAX_TRANSPORT_RETRIES
                and attempt < max_attempts
            ):
                transport_retries += 1
                logger.warning(
                    f"{log_prefix} ⚠ transient transport error on attempt "
                    f"{attempt}/{max_attempts} (transport_retry={transport_retries}/"
                    f"{_MAX_TRANSPORT_RETRIES}, agent={name}) — retrying in "
                    f"{_react_retry_delay(attempt)}s: {format_exception_message(exc)}"
                )
                await asyncio.sleep(_react_retry_delay(attempt))
                continue

            logger.error(f"{log_prefix} ❌ Failed: {format_exception_message(exc)}")
            if isinstance(exc, TimeoutError):
                return await _react_return_timeout_failure(
                    agent,
                    config,
                    query,
                    analysis,
                    wall_seconds=_react_llm_timeout(agent, config),
                    path=log_prefix,
                    steps_taken=attempt,
                    steps=steps,
                    messages=(response or {}).get("messages", []),
                )
            if _exception_indicates_tool_use_failed(exc):
                fail_note = (
                    "Provider rejected the model's tool output (tool_use_failed — usually prose instead of a structured tool call). "
                )
            elif exception_indicates_missing_user_query(exc):
                fail_note = "Chat template rejected the message list (no user query found). "
            elif exception_indicates_context_window_exceeded(exc):
                fail_note = "Context window exceeded after compaction retries. "
            elif isinstance(exc, ContextBudgetExceededError):
                fail_note = f"{exc} "
            elif exception_indicates_transient_transport_error(exc):
                fail_note = (
                    "HTTP transport disconnected (LLM or MCP proxy) after transport retries. "
                )
            else:
                fail_note = ""
            exc_str = format_exception_message(exc)
            return await _react_failure(
                agent,
                config,
                query,
                analysis,
                output=f"{fail_note}REACT execution failed: {exc_str}",
                steps_taken=attempt,
                steps=steps,
                messages=(response or {}).get("messages", []),
            )

    return await _react_failure(
        agent,
        config,
        query,
        analysis,
        output="REACT exhausted all retries without a result.",
        steps_taken=max_attempts,
        steps=steps,
    )


async def _handle_react_streaming(
    agent: dict,
    query: str | list[Any],
    analysis: QueryAnalysis,
    config: dict | None = None,
    event_queue: asyncio.Queue | None = None,
    *,
    stream_compact_retry_remaining: int = 1,
    initial_state: dict | None = None,
) -> ExecutionResult:
    """REACT with live token-by-token streaming via LangGraph astream_events.

    Uses the LangGraph agent's astream_events(version="v2") to capture:
    - on_chat_model_stream: individual LLM tokens → pushed as "token" events
    - on_tool_start: tool invocations → pushed as "tool_call" events with id
    - on_tool_end: tool results → pushed as "tool_result" events with matching id
    - on_chain_end: final state for response extraction

    On ``astream_events`` failure, continues via :func:`_run_react_ainvoke_with_retries`
    with the **same** ainvoke retry budget as the non-stream path (``attempt_offset=0``).
    Partial stream progress is preserved via ``initial_state`` only; tool_use_failed is
    not silently treated as a free extra attempt slice.
    """
    llm = agent["llm"]
    tools = agent["tools"]
    system_prompt = _react_system_prompt(agent)
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
        {**(config or {}), "recursion_limit": _react_recursion_limit(agent)},
    )
    state = (
        _react_invoke_state(agent, query, initial_state)
        if initial_state is not None
        else _react_invoke_state(agent, query, {"messages": _react_opening_messages(query)})
    )

    t0 = time.perf_counter()
    steps.append(
        _make_step(
            StepType.WORKER_START,
            "react_agent",
            input=text_from_user_turn(query),
            max_length=ml,
        )
    )
    final_response = None
    _tool_run_ids: dict[str, str] = {}
    _tool_arg_dicts: dict[str, dict[str, Any]] = {}
    tool_names = _react_tool_names(tools)
    _graph_wall_timeout = _react_graph_wall_timeout(agent)
    last_stream_kind: str | None = None

    try:
        async with asyncio.timeout(_graph_wall_timeout):
            async for event in react_agent.astream_events(state, config=invoke_config, version="v2"):
                kind = event["event"]
                last_stream_kind = kind

                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if event_queue:
                        reasoning, answer = split_stream_parts_from_chunk(chunk)
                        if reasoning:
                            await event_queue.put(
                                AgentEvent(
                                    type="token",
                                    data={"content": reasoning, "role": "reasoning"},
                                )
                            )
                        if answer and not (
                            answer.strip()
                            and tool_names
                            and _is_stray_tool_json_text(answer.strip(), tool_names)
                        ):
                            await event_queue.put(
                                AgentEvent(
                                    type="token",
                                    data={"content": answer, "role": "assistant"},
                                )
                            )

                elif kind == "on_tool_start":
                    run_id = event.get("run_id", "")
                    wire_id = _wire_tool_call_id_from_stream_event(event)
                    tool_name = event.get("name", "unknown")
                    tool_input = event.get("data", {}).get("input", {})
                    arg_dict = _tool_input_as_dict(tool_input)
                    _tool_arg_dicts[run_id] = arg_dict
                    _tool_run_ids[run_id] = tool_name
                    if event_queue:
                        await event_queue.put(
                            AgentEvent(
                                type="tool_call",
                                data=_agent_event_tool_data(
                                    tool_call_id=wire_id,
                                    tool_name=tool_name,
                                    input=_trunc(str(tool_input), ml),
                                    args=arg_dict,
                                ),
                            )
                        )
                    steps.append(
                        _make_step(
                            StepType.TOOL_CALL,
                            tool_name,
                            input=str(tool_input),
                            id=wire_id,
                            max_length=ml,
                            wire_emitted=bool(event_queue),
                        )
                    )

                elif kind == "on_tool_end":
                    run_id = event.get("run_id", "")
                    wire_id = _wire_tool_call_id_from_stream_event(event)
                    tool_name = _tool_run_ids.pop(run_id, event.get("name", "unknown"))
                    raw_out = event.get("data", {}).get("output")
                    args_rem = _tool_arg_dicts.pop(run_id, {})
                    skill_name: str | None = None
                    if tool_name == TOOL_LOAD_SKILL:
                        n = args_rem.get("name")
                        skill_name = n if isinstance(n, str) else None
                    if isinstance(raw_out, dict) and isinstance(raw_out.get("summary"), str):
                        out_payload: str | dict[str, object] = raw_out
                    else:
                        out_payload = _tool_output_to_wire_text(raw_out)
                    if event_queue:
                        await event_queue.put(
                            AgentEvent(
                                type="tool_result",
                                data=_agent_event_tool_data(
                                    tool_call_id=wire_id,
                                    tool_name=tool_name,
                                    output=out_payload,
                                    args=args_rem,
                                    **({"skill_name": skill_name} if skill_name else {}),
                                ),
                            )
                        )
                    step_out = (
                        raw_out["summary"]
                        if isinstance(raw_out, dict) and isinstance(raw_out.get("summary"), str)
                        else _tool_output_to_wire_text(raw_out)
                    )
                    steps.append(
                        _make_step(
                            StepType.TOOL_RESULT,
                            tool_name,
                            output=step_out,
                            id=wire_id,
                            max_length=ml,
                            wire_emitted=bool(event_queue),
                        )
                    )

                elif kind == "on_chain_end":
                    output_data = event.get("data", {}).get("output")
                    if isinstance(output_data, dict) and "messages" in output_data:
                        final_response = output_data

        dur = round((time.perf_counter() - t0) * 1000, 1)
        msgs = list((final_response or {}).get("messages", []))
        output = _extract_last_ai_message(final_response, tool_names=tool_names)
        stray_remaining = _STRAY_TOOL_JSON_RETRIES
        while (
            stray_remaining > 0
            and tool_names
            and _last_ai_message_is_stray_tool_json(msgs, tool_names)
        ):
            stray_remaining -= 1
            logger.warning(
                f"[React|stream] Stray tool JSON after tool run — recovery ainvoke "
                f"(retries left={stray_remaining}, agent={name})."
            )
            has_tool_result = any(isinstance(m, ToolMessage) for m in msgs)
            recovery_state = _react_invoke_state(
                agent,
                query,
                {
                    "messages": msgs
                    + [
                        HumanMessage(
                            content=_human_message_after_stray_tool_json(
                                tool_result_already_present=has_tool_result
                            )
                        )
                    ]
                },
            )
            _wall_timeout = _react_llm_timeout(agent, config)
            final_response = await asyncio.wait_for(
                cast(Any, react_agent).ainvoke(recovery_state, config=invoke_config),
                timeout=_wall_timeout,
            )
            msgs = list((final_response or {}).get("messages", []))
            recovered = _extract_last_ai_message(final_response, tool_names=tool_names)
            if recovered and event_queue:
                await event_queue.put(AgentEvent(type="token", data={"content": recovered}))
            output = recovered or output

        if not output or (tool_names and _is_stray_tool_json_text(output.strip(), tool_names)):
            output = (
                "I ran the tool but could not produce a final summary. "
                "Expand the tool row above for the raw result, or send another message to retry."
            )

        if not output:
            output = "No output produced."

        _stream_success = bool(output) and output not in (
            "No output produced.",
            "I ran the tool but could not produce a final summary. "
            "Expand the tool row above for the raw result, or send another message to retry.",
        )
        if tool_names and output and _is_stray_tool_json_text(output.strip(), tool_names):
            _stream_success = False

        usage = _extract_token_usage(final_response)
        llm_step = _make_step(
            StepType.LLM_CALL,
            "react_agent",
            input=text_from_user_turn(query),
            output=output,
            duration_ms=dur,
            max_length=ml,
            messages=len((final_response or {}).get("messages", [])),
            **_llm_step_metadata(agent, usage, phase="react_agent"),
        )
        steps.append(llm_step)
        await _emit_llm_call_step(config, event_queue, llm_step)
        steps.append(
            _make_step(
                StepType.WORKER_END,
                "react_agent",
                input=text_from_user_turn(query),
                output=output,
                duration_ms=dur,
                max_length=ml,
                signal=SignalType.SUCCESS.value,
            )
        )

        logger.event(f"[React|stream] Done — {len((final_response or {}).get('messages', []))} messages.")
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output=output,
            steps_taken=steps_taken_from_audit(steps),
            success=_stream_success,
            failure_class=None if _stream_success else "tool_error",
            retryable=not _stream_success,
            analysis=analysis,
            steps=steps,
            token_usage=usage,
            messages=(final_response or {}).get("messages", []),
        )

    except TimeoutError:
        return await _react_return_timeout_failure(
            agent,
            config,
            query,
            analysis,
            wall_seconds=_graph_wall_timeout,
            path="stream",
            steps_taken=steps_taken_from_audit(steps),
            steps=steps,
            messages=(final_response or {}).get("messages", []),
            event_queue=event_queue,
        )

    except asyncio.CancelledError:
        logger.event("[React|stream] Cancelled — stopping ReAct stream.")
        raise

    except UserAbort:
        logger.event("[React|stream] ✋ Aborted by user (tool not run).")
        msgs_stream: list[Any] = []
        if final_response is not None:
            try:
                msgs_stream = list((final_response or {}).get("messages", []))
            except Exception:
                msgs_stream = []
        return ExecutionResult(
            pattern_used=PatternType.REACT,
            query=query,
            output="Aborted",
            steps_taken=steps_taken_from_audit(steps),
            success=True,
            analysis=analysis,
            metadata={"user_aborted_tool": True},
            steps=steps,
            messages=msgs_stream,
        )

    except GraphRecursionError:
        return await _react_recursion_limit_failure(
            agent,
            config,
            query,
            analysis,
            path="stream",
            steps=steps,
            messages=(final_response or {}).get("messages", []),
            event_queue=event_queue,
            max_length=ml,
        )

    except Exception as exc:
        if isinstance(exc, TimeoutError):
            return await _react_return_timeout_failure(
                agent,
                config,
                query,
                analysis,
                wall_seconds=_graph_wall_timeout,
                path="stream",
                steps_taken=steps_taken_from_audit(steps),
                steps=steps,
                messages=(final_response or {}).get("messages", []),
                event_queue=event_queue,
            )
        root_msg = format_exception_message(exc)
        stream_ctx = f" last_event={last_stream_kind!r}" if last_stream_kind else ""
        from ..context.errors import ContextBudgetExceededError

        if isinstance(exc, ContextBudgetExceededError):
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=str(exc),
                steps_taken=steps_taken_from_audit(steps),
                success=False,
                failure_class="context",
                retryable=False,
                analysis=analysis,
                steps=steps,
                messages=(final_response or {}).get("messages", []) if isinstance(final_response, dict) else [],
                metadata={
                    "estimated_input_tokens": exc.estimated_tokens,
                    "budget": exc.budget,
                    "execution_path": "stream_context_budget",
                },
            )
        if (
            exception_indicates_transient_transport_error(exc)
            and stream_compact_retry_remaining > 0
        ):
            msgs = list(
                (final_response or {}).get("messages")
                or (initial_state or {}).get("messages")
                or _react_opening_messages(query)
            )
            compacted = _compact_react_state_for_context_pressure(agent, {"messages": msgs})
            if compacted is not None:
                before = estimate_messages_tokens(msgs)
                after = estimate_messages_tokens(compacted.get("messages") or [])
                if after < before:
                    logger.warning(
                        f"[React|stream] transport error — stream_compact_retry "
                        f"est_tokens {before} -> {after}{stream_ctx}"
                    )
                    return await _handle_react_streaming(
                        agent,
                        query,
                        analysis,
                        config=config,
                        event_queue=event_queue,
                        stream_compact_retry_remaining=stream_compact_retry_remaining - 1,
                        initial_state=compacted,
                    )
        if agent.get("strict_execution"):
            logger.warning(
                f"[React|stream] astream_events failed ({root_msg}){stream_ctx} — strict_execution, no ainvoke fallback"
            )
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=root_msg,
                steps_taken=steps_taken_from_audit(steps),
                success=False,
                failure_class="transport",
                retryable=True,
                analysis=analysis,
                steps=steps,
                messages=(final_response or {}).get("messages", []) if isinstance(final_response, dict) else [],
                metadata={"execution_path": "stream_failed_strict"},
            )
        logger.warning(
            f"[React|stream] astream_events failed ({root_msg}){stream_ctx} — "
            f"continuing via ainvoke retry loop for {name}"
        )
        try:
            from ..runtime.invocation_context import get_invocation_emitter

            _recovery_emitter = get_invocation_emitter()
            if _recovery_emitter is not None:
                _recovery_emitter.emit_orchestration_step(
                    depth=0,
                    pattern="REACT",
                    action="execution.recovery_path",
                    reason="stream_to_ainvoke",
                    error=root_msg[:500],
                )
        except Exception:
            pass
        initial_state: dict | None = None
        if isinstance(final_response, dict):
            msgs = final_response.get("messages")
            if msgs:
                initial_state = {"messages": list(msgs)}
        if _exception_indicates_tool_use_failed(exc):
            base = initial_state or {"messages": _react_opening_messages(query)}
            initial_state = _react_invoke_state(
                agent,
                query,
                {
                    "messages": list(base["messages"])
                    + [HumanMessage(content=_human_message_after_tool_use_failed(exc))]
                },
            )
        elif exception_indicates_missing_user_query(exc):
            base = initial_state or {"messages": _react_opening_messages(query)}
            initial_state = _react_invoke_state(
                agent,
                query,
                {
                    "messages": list(base["messages"])
                    + [HumanMessage(content=human_message_after_missing_user_query())]
                },
            )
        elif exception_indicates_context_window_exceeded(exc):
            compacted = _compact_react_state_for_context_pressure(agent, {"messages": list((initial_state or {}).get("messages") or _react_opening_messages(query))})
            if compacted is not None:
                initial_state = _react_invoke_state(agent, query, compacted)
            elif initial_state is not None:
                initial_state = _react_invoke_state(agent, query, initial_state)
        elif initial_state is not None:
            initial_state = _react_invoke_state(agent, query, initial_state)
        return await _run_react_ainvoke_with_retries(
            agent=agent,
            query=query,
            analysis=analysis,
            config=config,
            react_agent=react_agent,
            initial_state=initial_state,
            attempt_offset=0,
            collect_tool_steps=True,
            emit_tool_events_to_queue=True,
            log_prefix="[React|stream→ainvoke]",
        )


def _wire_tool_call_id_from_stream_event(event: Mapping[str, Any]) -> str:
    """Stable id for AGP ``tool.call.*`` — LangGraph ``run_id`` pairs start/end on the stream path."""
    run_id = event.get("run_id")
    if run_id is not None:
        s = str(run_id).strip()
        if s:
            return s
    return uuid4().hex


def _resolve_wire_tool_call_id_for_step(step: Any, tool_steps: list) -> str:
    """Match ``tool_result`` steps to a prior wire-emitted ``tool_call`` when ids differ (stream vs ainvoke)."""
    meta = step.metadata or {}
    raw = meta.get("id") or meta.get("tool_call_id")
    tcid = str(raw).strip() if raw is not None else ""
    if step.type == StepType.TOOL_RESULT:
        for cs in tool_steps:
            if cs.type != StepType.TOOL_CALL or cs.name != step.name:
                continue
            cm = cs.metadata or {}
            if not (cm.get("wire_emitted") or cm.get("_wire_emitted")):
                continue
            wired = cm.get("id") or cm.get("tool_call_id")
            if wired is not None and str(wired).strip():
                return str(wired).strip()
    return tcid or uuid4().hex


def _agent_event_tool_data(*, tool_call_id: str, tool_name: str, **extra: Any) -> dict[str, Any]:
    return {"tool_call_id": tool_call_id, "id": tool_call_id, "name": tool_name, **extra}


async def _emit_react_tool_steps_to_event_queue(agent: dict, tool_steps: list) -> None:
    """Emit tool_call / tool_result events for ``ainvoke`` paths (non-streaming HITL, stream fallback).

    Streaming ReAct + HITL uses ``astream_events`` directly; this backfills the queue when we fall
    back to ``ainvoke`` or use :func:`_handle_react_hitl``. Steps already marked ``wire_emitted``
    (partial stream progress) are skipped so tool_call is not duplicated; missing tool_result
    rows from the failed stream are still emitted.
    """
    queue = resolve_event_queue(agent)
    if not queue:
        return
    for step in tool_steps:
        if step.type not in (StepType.TOOL_CALL, StepType.TOOL_RESULT):
            continue
        meta = step.metadata or {}
        if meta.get("wire_emitted") or meta.get("_wire_emitted"):
            continue
        event_type = "tool_call" if step.type == StepType.TOOL_CALL else "tool_result"
        wire_id = _resolve_wire_tool_call_id_for_step(step, tool_steps)
        payload: dict[str, Any] = {
            "name": step.name,
            "input": step.input,
            "output": step.output,
            **(step.metadata or {}),
            "id": wire_id,
            "tool_call_id": wire_id,
        }
        await queue.put(AgentEvent(type=event_type, data=payload))


async def _handle_react_hitl(
    agent: dict,
    llm,
    tools: list,
    system_prompt: str,
    query: str | list[Any],
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
    coalescer = agent.get("_hitl_tool_coalescer")
    if coalescer is None:
        coalescer = build_default_hitl_coalescer()
        agent["_hitl_tool_coalescer"] = coalescer
    approval_middleware = HumanApprovalMiddleware(
        interrupt_before_tools=interrupt_before_tools,
        user_callback=user_callback,
        agent_name=name,
        tool_allowlist=agent.get("_hitl_tool_allowlist"),
        hitl_coalescer=coalescer,
    )

    react_agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
        middleware=_langchain_react_middleware(agent, approval_middleware),
    )

    invoke_config = {
        **(incoming_config or {}),
        "recursion_limit": _react_recursion_limit(agent),
    }
    steps: list = (incoming_config or {}).get("_steps", [])
    ml = agent.get("max_step_output_length", 0)
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
            t0 = time.perf_counter()
            _wall_timeout = _react_llm_timeout(agent, incoming_config)
            await _acquire_transport_llm(agent)
            response = await asyncio.wait_for(
                cast(Any, react_agent).ainvoke(
                    {"messages": messages},
                    config=invoke_config,
                ),
                timeout=_wall_timeout,
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
                await asyncio.sleep(_react_retry_delay(attempt))
                messages = list(msgs) + [
                    HumanMessage(
                        content=_human_message_after_stray_tool_json(
                            tool_result_already_present=any(
                                isinstance(m, ToolMessage) for m in msgs
                            )
                        )
                    )
                ]
                continue

            hitl_tool_steps: list = []
            _collect_tool_steps(response, hitl_tool_steps, max_length=ml)
            steps.extend(hitl_tool_steps)
            await _emit_react_tool_steps_to_event_queue(agent, hitl_tool_steps)

            output = _extract_last_ai_message(response)
            if not output:
                output = "No output produced."

            dur = round((time.perf_counter() - t0) * 1000, 1)
            usage = _extract_token_usage(response)
            llm_step = _make_step(
                StepType.LLM_CALL,
                "react_agent",
                input=text_from_user_turn(query),
                output=output,
                duration_ms=dur,
                max_length=ml,
                messages=len((response or {}).get("messages", [])),
                **_llm_step_metadata(agent, usage, phase="react_agent"),
            )
            steps.append(llm_step)
            queue = resolve_event_queue(agent, incoming_config)
            await _emit_llm_call_step(incoming_config, queue, llm_step)

            logger.event(f"[React|HITL] ✅ Done — {len(output)} chars.")
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=query,
                output=output,
                steps_taken=steps_taken_from_audit(steps),
                success=True,
                analysis=analysis,
                steps=steps,
                token_usage=usage,
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
            return await _react_recursion_limit_failure(
                agent,
                incoming_config,
                query,
                analysis,
                path="[React|HITL]",
                steps=steps,
                messages=(response or {}).get("messages", []),
                max_length=ml,
            )

        except TimeoutError:
            return await _react_return_timeout_failure(
                agent,
                incoming_config,
                query,
                analysis,
                wall_seconds=_react_llm_timeout(agent, incoming_config),
                path="[React|HITL]",
                steps_taken=attempt,
                steps=steps,
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
                    await asyncio.sleep(_react_retry_delay(attempt))
                    messages.append(HumanMessage(content=_human_message_after_tool_use_failed(exc)))
                    response = None
                    continue
                if user_cb and user_recovery_budget > 0:
                    user_recovery_budget -= 1
                    decision = await _user_decision_after_tool_use_failed(user_cb, exc)
                    if decision == "retry":
                        max_attempts = min(
                            max_attempts + batch_size,
                            REACT_ABSOLUTE_MAX_AINVOKE_ATTEMPTS,
                        )
                        if max_attempts <= attempt:
                            logger.error(
                                "[React|HITL] User retry requested but absolute attempt cap "
                                f"({REACT_ABSOLUTE_MAX_AINVOKE_ATTEMPTS}) reached."
                            )
                            break
                        silent_in_batch = 0
                        logger.event(
                            f"[React|HITL] User authorized another model-turn batch after "
                            f"REACT_TOOL_USE_FAILED (recovery rounds left={user_recovery_budget})."
                        )
                        await asyncio.sleep(_react_retry_delay(attempt))
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
            exc_str = format_exception_message(exc)
            return await _react_failure(
                agent,
                incoming_config,
                query,
                analysis,
                output=f"{fail_note}REACT HITL execution failed: {exc_str}",
                steps_taken=attempt,
                steps=list(steps),
                messages=(response or {}).get("messages", []),
            )

    return await _react_failure(
        agent,
        incoming_config,
        query,
        analysis,
        output="REACT HITL exhausted tool-call retries.",
        steps_taken=max_attempts,
        steps=list(steps),
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


def _tool_output_to_wire_text(raw_out: Any, *, max_length: int = 0) -> str:
    """Serialize tool return values for wire previews (never ``str(ToolMessage)`` repr)."""
    from langchain_core.messages import ToolMessage

    if raw_out is None:
        text = ""
    elif isinstance(raw_out, str):
        text = raw_out
    elif isinstance(raw_out, ToolMessage):
        text = _ai_message_content_to_text(raw_out.content)
    elif isinstance(raw_out, dict) and isinstance(raw_out.get("summary"), str):
        return raw_out["summary"] if not max_length else _trunc(raw_out["summary"], max_length)
    elif hasattr(raw_out, "content"):
        text = _ai_message_content_to_text(getattr(raw_out, "content"))
    else:
        text = str(raw_out or "")
    return _trunc(text, max_length) if max_length else text


def _strip_agloom_tool_result_envelope(text: str) -> str:
    import re

    t = text
    pat = re.compile(r"^\[agloom:tool_result\]\s*complete=(?:true|false)\s*\n?", re.IGNORECASE)
    while pat.match(t):
        t = pat.sub("", t, count=1)
    return t.strip()


def _fallback_output_from_messages(messages: list[Any], *, tool_names: frozenset[str]) -> str | None:
    """When the model ends on stray JSON, surface the last ``read_file`` tool body for the user."""
    if "read_file" not in tool_names:
        return None
    from langchain_core.messages import ToolMessage

    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage):
            continue
        if (msg.name or "") != "read_file":
            continue
        body = _strip_agloom_tool_result_envelope(_ai_message_content_to_text(msg.content))
        if body:
            return body
    return None


def _ai_message_content_to_text(content: Any) -> str:
    """Normalize ``AIMessage.content`` (str, None, or LC multimodal blocks) to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                btype = block.get("type")
                if btype in ("image", "image_url", "input_audio", "video", "file"):
                    continue
                if btype == "text" and "text" in block:
                    parts.append(str(block.get("text", "")))
                elif isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "".join(parts).strip()
    return str(content).strip()


def _message_tool_like_calls(msg: Any) -> tuple[list | None, list | None]:
    """Return (tool_calls, invalid_tool_calls) for AIMessage instances or LC dict wire shapes."""
    if isinstance(msg, AIMessage):
        tc = getattr(msg, "tool_calls", None)
        inv = getattr(msg, "invalid_tool_calls", None)
        return (list(tc) if tc else None, list(inv) if inv else None)
    if isinstance(msg, dict):
        inner = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        if not isinstance(inner, dict):
            return (None, None)
        tc = inner.get("tool_calls")
        if tc is None:
            tc = msg.get("tool_calls")
        inv = inner.get("invalid_tool_calls")
        if inv is None:
            inv = msg.get("invalid_tool_calls")
        return (
            list(tc) if isinstance(tc, list) and tc else None,
            list(inv) if isinstance(inv, list) and inv else None,
        )
    return (None, None)


def _extract_last_ai_message(
    response: dict | None,
    *,
    tool_names: frozenset[str] | None = None,
) -> str:
    """Walk messages in reverse — last AIMessage with user-visible text.

    Skips **tool-only** assistant turns (``tool_calls`` present and no extractable text).
    When the model sends **prose and tool_calls in the same** ``AIMessage`` (e.g. a short
    preamble before calling tools), the preamble is treated as valid output.
    Skips stray JSON tool blobs (Groq/Llama text-mode tool intent).

    Handles multimodal ``content`` lists and LangChain ``type: "ai"`` dict messages.
    """
    if not isinstance(response, dict):
        return ""
    for msg in reversed(response.get("messages", [])):
        content: Any = None
        if isinstance(msg, AIMessage):
            content = msg.content
        elif isinstance(msg, dict):
            mtype = msg.get("type")
            role = msg.get("role")
            if mtype not in ("ai", "assistant", "AIMessage") and role != "assistant":
                continue
            inner = msg.get("data") if isinstance(msg.get("data"), dict) else msg
            if isinstance(inner, dict):
                content = inner.get("content")
                if content is None:
                    content = msg.get("content")
            else:
                content = msg.get("content")
        else:
            continue

        tool_calls, invalid_tool_calls = _message_tool_like_calls(msg)
        if invalid_tool_calls:
            continue
        text = _ai_message_content_to_text(content)
        if tool_calls and not text:
            continue
        if text and tool_names and _is_stray_tool_json_text(text, tool_names):
            continue
        if text:
            return text
    return ""
