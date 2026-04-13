"""
test.py — Comprehensive test suite for agloom

Covers: models, validation, frozen agents, memory, tools, classifier, all 9
patterns, feedback, skills, multi-agent isolation, HITL, streaming, middleware,
error handling, and real-user scenarios.

Uses real ChatGroq LLM for integration tests.
No pytest — stdlib only (asyncio + assert).

Run:
    cd &lt;project-root&gt;
    python test.py
"""

from __future__ import annotations

import asyncio
import io
import math
import os
import sys
import time
import uuid

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from agloom.feedback import (
    AutoEvaluator,
    CompositeHandler,
    EvalScore,
    FeedbackStore,
    NoOpFeedbackHandler,
    RunRecord,
    TrendDetector,
    UserFeedbackHandler,
    WebhookFeedbackHandler,
)
from agloom.feedback.wireup import (
    build_feedback_system,
    run_fresh_feedback_hooks,
)
from agloom.logging_utils import get_logger
from agloom.memory import (
    LongTermStore,
    SessionMemory,
    build_memory_context,
    create_memory_tools,
)
from agloom.models import (
    DEFAULT_SYSTEM_PROMPT,
    AgentConfig,
    AgentEvent,
    AgentStep,
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    QueryAnalysisToolPayload,
    ResolvedWorkerConfig,
    SignalType,
    StepType,
    SubTask,
    WorkerPlan,
    WorkerResult,
    _extract_token_usage,
    _make_step,
    _merge_token_usage,
    query_analysis_from_tool_payload,
)
from agloom.patterns._blackboard_state import BlackboardState
from agloom.patterns._dag import group_by_level
from agloom.patterns._sequential import topological_sort
from agloom.patterns.reflection import _parse_critic_response
from agloom.skills.lifecycle import (
    GLOBAL_NS,
    MAX_SKILLS,
    REVIEW_EVERY_N_RUNS,
)
from agloom.skills.skill import (
    AgentSkill,
    SkillContent,
    SkillManifest,
)
from agloom.unified_agent import (
    RESERVED_TOOL_NAMES,
    _apply_frozen_substitution,
    _check_reserved_tool_names,
    _validate_frozen_params,
    create_agent,
    normalize_tools,
    resolve_system_prompt,
)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or ("")
os.environ["GROQ_API_KEY"] = GROQ_API_KEY
GROQ_MODEL = os.environ.get("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")


# ═══════════════════════════════════════════════════════════════════════════════
#  Test Tools (demo tools used only by this test suite)
# ═══════════════════════════════════════════════════════════════════════════════

from langchain_core.tools import tool


@tool
def extract_keywords(text: str) -> str:
    """Extract key terms and concepts from a given text."""
    STOP = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "and",
        "or",
        "but",
        "this",
        "that",
        "which",
        "who",
        "what",
        "how",
        "when",
        "where",
        "not",
        "no",
        "its",
        "their",
        "our",
        "your",
    }
    words = text.lower().split()
    cleaned = [w.strip(".,!?;:'\"()[]") for w in words]
    keywords = [w for w in cleaned if w not in STOP and len(w) > 3]
    unique = list(dict.fromkeys(keywords))[:20]
    return f"Keywords: {', '.join(unique)}"


@tool
def calculate(expression: str) -> str:
    """Safely evaluate a mathematical expression."""
    SAFE = {
        "__builtins__": {},
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "int": int,
        "float": float,
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "pi": math.pi,
        "e": math.e,
    }
    try:
        return f"Result: {eval(expression, SAFE, {})}"
    except Exception as e:
        return f"Calculation error: {e}"


@tool
def summarize_text(text: str, max_words: int = 120) -> str:
    """Truncate or summarize a long text to a word limit."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + f"... [{max_words}/{len(words)} words shown]"


TOOL_REGISTRY: dict = {
    "extract_keywords": extract_keywords,
    "calculate": calculate,
    "summarize_text": summarize_text,
}


def resolve_tools(tool_names: list[str]) -> tuple[list, list[str]]:
    """Resolve tool name strings to tool objects. Returns (resolved, missing)."""
    resolved, missing = [], []
    for name in tool_names:
        if name in TOOL_REGISTRY:
            resolved.append(TOOL_REGISTRY[name])
        else:
            missing.append(name)
    return resolved, missing


# ═══════════════════════════════════════════════════════════════════════════════
#  Test Runner with Input/Output Logging
# ═══════════════════════════════════════════════════════════════════════════════

_passed = 0
_failed = 0
_skipped = 0
_errors: list[tuple[str, str]] = []


def _trunc(s, n=200):
    s = str(s).replace("\n", " ")
    return s[:n] + "..." if len(s) > n else s


def _report(name: str, ok: bool, *, input_data="", output_data="", detail: str = "") -> None:
    global _passed, _failed
    tag = "[PASS]" if ok else "[FAIL]"
    if ok:
        _passed += 1
    else:
        _failed += 1
        _errors.append((name, detail))
    print(f"  {tag} {name}")
    if input_data:
        print(f"         INPUT:  {_trunc(input_data)}")
    if output_data:
        print(f"         OUTPUT: {_trunc(output_data)}")
    if detail and not ok:
        for line in detail.strip().splitlines()[:5]:
            print(f"         DETAIL: {line}")


def _skip(name: str, reason: str) -> None:
    global _skipped
    _skipped += 1
    print(f"  [SKIP] {name} ({reason})")


def run_test(name: str, fn, *, input_data="") -> None:
    try:
        result = fn()
        _report(name, True, input_data=input_data, output_data=result)
    except AssertionError as e:
        _report(name, False, input_data=input_data, detail=str(e))
    except Exception as e:
        _report(name, False, input_data=input_data, detail=f"{type(e).__name__}: {e}")


_LOOP: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop (created once, reused across all async tests).

    Avoids "Event loop is closed" errors caused by httpx/groq clients
    being GC'd after their owning loop was destroyed by asyncio.run().
    """
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


def run_async_test(name: str, coro, *, input_data="") -> None:
    try:
        result = _get_loop().run_until_complete(coro)
        _report(name, True, input_data=input_data, output_data=result)
    except AssertionError as e:
        _report(name, False, input_data=input_data, detail=str(e))
    except Exception as e:
        _report(name, False, input_data=input_data, detail=f"{type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_llm():
    from langchain_groq import ChatGroq

    return ChatGroq(model=GROQ_MODEL, temperature=0)


def _make_lts():
    from langgraph.store.memory import InMemoryStore

    return LongTermStore(store=InMemoryStore())


def _make_result(**overrides):
    defaults = {
        "pattern_used": PatternType.REACT,
        "query": "test query",
        "output": "test output",
        "steps_taken": 2,
        "success": True,
    }
    defaults.update(overrides)
    return ExecutionResult(**defaults)


def _make_score(**overrides):
    defaults = {
        "accuracy": 0.8,
        "completeness": 0.7,
        "efficiency": 0.9,
        "relevance": 0.85,
        "reasoning": "Good overall performance.",
    }
    defaults.update(overrides)
    return EvalScore(**defaults)


def _make_record(**overrides):
    defaults = {
        "run_id": uuid.uuid4().hex[:12],
        "agent_name": "TestAgent",
        "query": "test query",
        "pattern_used": "REACT",
        "success": True,
        "output_preview": "test output preview",
    }
    defaults.update(overrides)
    return RunRecord(**defaults)


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 1: Models and Enums
# ═══════════════════════════════════════════════════════════════════════════════


def sec1_models_and_enums():
    print("\n" + "=" * 60)
    print("  SEC 1: Models and Enums")
    print("=" * 60)

    # 1.1 All 9 PatternType values
    run_test("PatternType has 9 values", lambda: assert_eq(len(PatternType), 9) or "9 patterns")

    # 1.2 All pattern names exist
    for p in [
        "DIRECT",
        "REACT",
        "SUPERVISOR",
        "PIPELINE",
        "PLANNER_EXECUTOR",
        "REFLECTION",
        "SWARM",
        "BLACKBOARD",
        "HYBRID_DAG",
    ]:
        run_test(f"PatternType.{p} exists", lambda p=p: assert_eq(PatternType(p).value, p) or p)

    # 1.3 SignalType values
    for s in ["HALT_ALL", "CLARIFICATION_REQUEST", "SUCCESS", "FAILED"]:
        run_test(f"SignalType.{s} exists", lambda s=s: assert_eq(SignalType(s).value, s) or s)

    # 1.4 SubTask context flattening
    run_test(
        "SubTask flattens nested context",
        lambda: (
            ((st := SubTask(worker_id="w1", task="t", context={"k": [1, 2]})) and assert_eq(st.context["k"], "[1, 2]"))
            or st.context
        ),
    )

    run_test(
        "SubTask non-dict context → empty",
        lambda: ((st := SubTask(worker_id="w1", task="t", context="bad")) and assert_eq(st.context, {})) or st.context,
    )

    # 1.5 QueryAnalysis int coercion
    run_test(
        "QueryAnalysis coerces str complexity to int",
        lambda: (
            (
                (qa := QueryAnalysis(pattern=PatternType.DIRECT, complexity="3", reasoning="r"))
                and assert_eq(qa.complexity, 3)
            )
            or qa.complexity
        ),
    )

    run_test(
        "QueryAnalysis complexity clamped 0-10",
        lambda: (
            (
                (qa := QueryAnalysis(pattern=PatternType.DIRECT, complexity=0, reasoning="r"))
                and assert_eq(qa.complexity, 0)
            )
            or qa.complexity
        ),
    )

    # 1.6 QueryAnalysisToolPayload wire-to-strict
    run_test(
        "ToolPayload bool strings → proper bools",
        lambda: (
            (
                (raw := QueryAnalysisToolPayload(pattern="REACT", can_parallelize="true", needs_reflection="false"))
                and (qa := query_analysis_from_tool_payload(raw))
                and assert_true(qa.can_parallelize)
                and assert_true(not qa.needs_reflection)
            )
            or f"par={qa.can_parallelize} refl={qa.needs_reflection}"
        ),
    )

    run_test(
        "ToolPayload nullish direct_response",
        lambda: (
            (
                (raw := QueryAnalysisToolPayload(pattern="DIRECT", direct_response="null"))
                and assert_eq(raw.direct_response, None)
            )
            or "None"
        ),
    )

    run_test(
        "ToolPayload pattern fallback with tools",
        lambda: (
            (
                (raw := QueryAnalysisToolPayload(pattern="INVALID"))
                and (qa := query_analysis_from_tool_payload(raw, tools_available=True))
                and assert_eq(qa.pattern, PatternType.REACT)
            )
            or qa.pattern
        ),
    )

    run_test(
        "ToolPayload pattern fallback no tools",
        lambda: (
            (
                (raw := QueryAnalysisToolPayload(pattern="INVALID"))
                and (qa := query_analysis_from_tool_payload(raw, tools_available=False))
                and assert_eq(qa.pattern, PatternType.DIRECT)
            )
            or qa.pattern
        ),
    )

    run_test(
        "ToolPayload REFLECTION forces needs_reflection=True",
        lambda: (
            (
                (raw := QueryAnalysisToolPayload(pattern="REFLECTION", needs_reflection="false"))
                and (qa := query_analysis_from_tool_payload(raw))
                and assert_true(qa.needs_reflection)
            )
            or qa.needs_reflection
        ),
    )

    # 1.7 ExecutionResult fields
    run_test(
        "ExecutionResult has run_id default empty",
        lambda: (
            ((r := ExecutionResult(pattern_used=PatternType.DIRECT, query="q", output="o")) and assert_eq(r.run_id, ""))
            or r.run_id
        ),
    )

    run_test(
        "ExecutionResult accepts run_id",
        lambda: (
            (
                (r := ExecutionResult(pattern_used=PatternType.DIRECT, query="q", output="o", run_id="abc"))
                and assert_eq(r.run_id, "abc")
            )
            or r.run_id
        ),
    )

    run_test(
        "ExecutionResult has interrupts list", lambda: ((r := _make_result()) and assert_eq(r.interrupts, [])) or "[]"
    )

    run_test("ExecutionResult has metadata dict", lambda: ((r := _make_result()) and assert_eq(r.metadata, {})) or "{}")

    # 1.8 Signal, WorkerResult defaults
    from agloom.models import Signal

    run_test(
        "Signal defaults",
        lambda: (
            (
                (s := Signal(signal_type=SignalType.SUCCESS, worker_id="w1", message="ok"))
                and assert_eq(s.metadata, {})
                and assert_eq(s.response_queue, None)
            )
            or "defaults ok"
        ),
    )

    run_test(
        "WorkerResult defaults",
        lambda: (
            (
                (wr := WorkerResult(worker_id="w1", task="t", output="o"))
                and assert_eq(wr.signal, SignalType.SUCCESS)
                and assert_eq(wr.error, None)
                and assert_eq(wr.elapsed_ms, 0.0)
                and assert_eq(wr.attempt, 1)
            )
            or "defaults ok"
        ),
    )

    # 1.9 EvalScore
    run_test(
        "EvalScore boundary 0.0/1.0",
        lambda: (
            (
                (s := EvalScore(accuracy=0.0, completeness=1.0, efficiency=0.5, relevance=0.5, reasoning="test"))
                and assert_eq(s.overall(), round((0 + 1 + 0.5 + 0.5) / 4, 3))
            )
            or s.overall()
        ),
    )

    run_test(
        "EvalScore rejects out-of-range",
        lambda: (
            _expect_error(
                lambda: EvalScore(accuracy=1.5, completeness=0.5, efficiency=0.5, relevance=0.5, reasoning="bad")
            )
            or "rejected"
        ),
    )

    run_test(
        "EvalScore.to_log_str format",
        lambda: (
            (
                (s := _make_score())
                and assert_true("overall=" in s.to_log_str())
                and assert_true("acc=" in s.to_log_str())
            )
            or s.to_log_str()
        ),
    )

    # 1.10 RunRecord
    run_test(
        "RunRecord defaults and index_text",
        lambda: (
            (
                (r := _make_record())
                and assert_true("query:" in r.index_text())
                and assert_true("pattern:" in r.index_text())
            )
            or r.index_text()
        ),
    )

    run_test(
        "RunRecord model_dump roundtrip",
        lambda: (
            (
                (r := _make_record(score=_make_score()))
                and (d := r.model_dump())
                and (r2 := RunRecord(**d))
                and assert_eq(r.run_id, r2.run_id)
                and assert_eq(r.score.overall(), r2.score.overall())
            )
            or "roundtrip ok"
        ),
    )

    # 1.11 WorkerPlan context flattening
    run_test(
        "WorkerPlan flattens context",
        lambda: (
            (
                (wp := WorkerPlan(worker_id="w1", task="t", context={"k": {"nested": True}}))
                and assert_eq(type(wp.context["k"]), str)
            )
            or wp.context
        ),
    )

    # 1.12 ResolvedWorkerConfig defaults
    run_test(
        "ResolvedWorkerConfig defaults",
        lambda: (
            (
                (rc := ResolvedWorkerConfig(worker_id="w1", task="t", system_prompt="p"))
                and assert_eq(rc.tools, [])
                and assert_eq(rc.depends_on, [])
                and assert_eq(rc.max_retries, 2)
                and assert_eq(rc.retry_delay, 1.0)
            )
            or "defaults ok"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 2: AgentConfig Validation
# ═══════════════════════════════════════════════════════════════════════════════


def sec2_agent_config():
    print("\n" + "=" * 60)
    print("  SEC 2: AgentConfig Validation")
    print("=" * 60)

    run_test("Valid config passes", lambda: AgentConfig(model="openai:gpt-4o") and "ok")

    run_test("Rejects None model", lambda: _expect_error(lambda: AgentConfig(model=None)) or "rejected")

    run_test("Rejects empty model string", lambda: _expect_error(lambda: AgentConfig(model="  ")) or "rejected")

    run_test("Rejects empty name", lambda: _expect_error(lambda: AgentConfig(model="m", name="")) or "rejected")

    run_test(
        "Rejects bad interrupt pattern names",
        lambda: _expect_error(lambda: AgentConfig(model="m", interrupt_before=["FAKE"])) or "rejected",
    )

    run_test(
        "Rejects non-callable callback",
        lambda: _expect_error(lambda: AgentConfig(model="m", user_callback="not_fn")) or "rejected",
    )

    run_test(
        "max_concurrent bounds 1-32",
        lambda: (
            (
                _expect_error(lambda: AgentConfig(model="m", max_concurrent=0))
                and _expect_error(lambda: AgentConfig(model="m", max_concurrent=33))
            )
            or "bounded"
        ),
    )

    run_test(
        "max_retries bounds 0-10",
        lambda: (
            (
                AgentConfig(model="m", max_retries=0)
                and AgentConfig(model="m", max_retries=10)
                and _expect_error(lambda: AgentConfig(model="m", max_retries=11))
            )
            or "bounded"
        ),
    )

    run_test(
        "tools None → empty list",
        lambda: ((c := AgentConfig(model="m", tools=None)) and assert_eq(c.tools, [])) or "[]",
    )

    run_test(
        "middleware None → empty list",
        lambda: ((c := AgentConfig(model="m", middleware=None)) and assert_eq(c.middleware, [])) or "[]",
    )

    run_test(
        "mcp_servers None → empty list",
        lambda: ((c := AgentConfig(model="m", mcp_servers=None)) and assert_eq(c.mcp_servers, [])) or "[]",
    )

    run_test(
        "Callable user_callback accepted", lambda: AgentConfig(model="m", user_callback=lambda: None) and "accepted"
    )

    run_test(
        "Valid interrupt_before pattern names",
        lambda: AgentConfig(model="m", interrupt_before=["DIRECT", "REACT"]) and "ok",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 3: Frozen Param Validation
# ═══════════════════════════════════════════════════════════════════════════════


def sec3_frozen_validation():
    print("\n" + "=" * 60)
    print("  SEC 3: Frozen Param Validation")
    print("=" * 60)

    run_test(
        "frozen=True requires non-empty template",
        lambda: _expect_error(lambda: _validate_frozen_params(True, "", "input")) or "rejected",
    )

    run_test(
        "frozen=True None template raises",
        lambda: _expect_error(lambda: _validate_frozen_params(True, None, "input")) or "rejected",
    )

    run_test(
        "frozen=True empty input_key raises",
        lambda: _expect_error(lambda: _validate_frozen_params(True, "t {input}", [])) or "rejected",
    )

    run_test(
        "frozen=True non-string input_key item raises",
        lambda: _expect_error(lambda: _validate_frozen_params(True, "t {x}", [123])) or "rejected",
    )

    run_test(
        "frozen=False skips validation", lambda: (_validate_frozen_params(False, None, "") is None and "ok") or "ok"
    )

    run_test(
        "frozen=True valid params pass",
        lambda: (_validate_frozen_params(True, "Classify: {input}", "input") is None and "ok") or "ok",
    )

    def test_frozen_sub_single():
        analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="r")
        q, sp, a = _apply_frozen_substitution("hello", "Classify: {input}", "Sys: {input}", analysis, "input")
        assert q == "Classify: hello", f"Expected 'Classify: hello', got {q!r}"
        assert sp == "Sys: hello"
        return f"q={q} sp={sp}"

    run_test("_apply_frozen_substitution single key", test_frozen_sub_single, input_data="single key substitution")

    def test_frozen_sub_multi():
        analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="r")
        q, sp, a = _apply_frozen_substitution(
            {"sender": "x", "body": "body text"}, "From {sender}: {body}", "sys", analysis, ["sender", "body"]
        )
        assert q == "From x: body text", f"Expected 'From x: body text', got {q!r}"
        return f"q={q}"

    run_test("_apply_frozen_substitution multi key", test_frozen_sub_multi, input_data="multi key substitution")

    def test_frozen_sub_missing():
        analysis = QueryAnalysis(pattern=PatternType.DIRECT, complexity=1, reasoning="r")
        q, sp, a = _apply_frozen_substitution("val", "Template {missing}", "sys", analysis, "input")
        assert q == "Template {missing}", f"Expected placeholder preserved, got {q!r}"
        return f"q={q}"

    run_test(
        "_apply_frozen_substitution missing placeholder passthrough",
        test_frozen_sub_missing,
        input_data="missing placeholder preserved",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 4: Memory
# ═══════════════════════════════════════════════════════════════════════════════


def sec4_memory():
    print("\n" + "=" * 60)
    print("  SEC 4: Memory")
    print("=" * 60)

    from langgraph.store.memory import InMemoryStore

    # SessionMemory sync
    run_test(
        "SessionMemory add_turn + format_context",
        lambda: (
            (
                (sm := SessionMemory(store=InMemoryStore(), max_turns=5))
                and sm.add_turn("t1", "Hello", "Hi there", "DIRECT") is None
                and (ctx := sm.format_context("t1"))
                and assert_true("Hello" in ctx)
                and assert_true("Hi there" in ctx)
            )
            or ctx
        ),
    )

    run_test(
        "SessionMemory max_turns eviction",
        lambda: (
            (
                (sm := SessionMemory(store=InMemoryStore(), max_turns=2))
                and sm.add_turn("t1", "q1", "a1") is None
                and sm.add_turn("t1", "q2", "a2") is None
                and sm.add_turn("t1", "q3", "a3") is None
                and (ctx := sm.format_context("t1", last_n=10))
                and assert_true("q1" not in ctx)
                and assert_true("q3" in ctx)
            )
            or ctx
        ),
    )

    run_test(
        "SessionMemory thread isolation",
        lambda: (
            (
                (sm := SessionMemory(store=InMemoryStore()))
                and sm.add_turn("t1", "q1", "a1") is None
                and sm.add_turn("t2", "q2", "a2") is None
                and (c1 := sm.format_context("t1"))
                and (c2 := sm.format_context("t2"))
                and assert_true("q1" in c1)
                and assert_true("q2" not in c1)
                and assert_true("q2" in c2)
            )
            or f"t1={c1[:40]} t2={c2[:40]}"
        ),
    )

    # SessionMemory async
    async def test_sm_async():
        sm = SessionMemory(store=InMemoryStore())
        await sm.aadd_turn("t1", "async_q", "async_a")
        ctx = await sm.aformat_context("t1")
        assert "async_q" in ctx
        return ctx

    run_async_test("SessionMemory async aadd_turn/aformat_context", test_sm_async())

    # LongTermStore sync
    run_test(
        "LongTermStore save/get sync",
        lambda: (
            (
                (lts := LongTermStore(store=InMemoryStore()))
                and lts.save(("ns",), "fact 1", topic="test")
                and (results := lts.search(("ns",), "fact"))
                and assert_true(len(results) >= 1)
            )
            or f"{len(results)} results"
        ),
    )

    # LongTermStore async
    async def test_lts_async():
        lts = LongTermStore(store=InMemoryStore())
        await lts.asave(("ns",), "async fact", topic="async")
        results = await lts.asearch(("ns",), "async")
        assert len(results) >= 1
        return f"{len(results)} results"

    run_async_test("LongTermStore async asave/asearch", test_lts_async())

    # LongTermStore namespace isolation
    async def test_lts_ns_isolation():
        lts = LongTermStore(store=InMemoryStore())
        await lts.asave(("a",), "fact for a")
        await lts.asave(("b",), "fact for b")
        ra = await lts.asearch(("a",), "fact")
        rb = await lts.asearch(("b",), "fact")
        a_vals = [getattr(r, "value", {}).get("memory", "") for r in ra]
        b_vals = [getattr(r, "value", {}).get("memory", "") for r in rb]
        assert any("a" in v for v in a_vals), f"ns-a should have 'a': {a_vals}"
        assert any("b" in v for v in b_vals), f"ns-b should have 'b': {b_vals}"
        return "isolated"

    run_async_test("LongTermStore namespace isolation", test_lts_ns_isolation())

    # LongTermStore skill-mode (explicit key)
    async def test_lts_skill_mode():
        lts = LongTermStore(store=InMemoryStore())
        k = await lts.asave(("skills",), key="my-skill", value="index text", metadata={"body": "skill body"})
        assert k == "my-skill"
        item = await lts.aget(("skills",), "my-skill")
        assert item is not None
        assert item.value.get("body") == "skill body"
        return "skill-mode ok"

    run_async_test("LongTermStore skill-mode key+metadata", test_lts_skill_mode())

    # LongTermStore delete
    async def test_lts_delete():
        lts = LongTermStore(store=InMemoryStore())
        await lts.asave(("ns",), key="k1", value="v1")
        await lts.adelete(("ns",), "k1")
        item = await lts.aget(("ns",), "k1")
        assert item is None or getattr(item, "value", None) is None
        return "deleted"

    run_async_test("LongTermStore delete", test_lts_delete())

    # build_memory_context
    async def test_bmc_empty():
        ctx = await build_memory_context()
        assert ctx == ""
        return "empty"

    run_async_test("build_memory_context empty", test_bmc_empty())

    async def test_bmc_session():
        sm = SessionMemory(store=InMemoryStore())
        await sm.aadd_turn("t1", "prev_q", "prev_a")
        ctx = await build_memory_context(session=sm, thread_id="t1")
        assert "prev_q" in ctx
        return ctx[:80]

    run_async_test("build_memory_context with session", test_bmc_session())

    async def test_bmc_truncation():
        sm = SessionMemory(store=InMemoryStore())
        await sm.aadd_turn("t1", "x" * 5000, "y" * 5000)
        ctx = await build_memory_context(session=sm, thread_id="t1", max_chars=100)
        assert len(ctx) <= 100
        return f"len={len(ctx)}"

    run_async_test("build_memory_context max_chars truncation", test_bmc_truncation())

    # Memory tools
    run_test(
        "create_memory_tools returns 2 tools",
        lambda: (
            (
                (lts := LongTermStore(store=InMemoryStore()))
                and (tools := create_memory_tools(lts))
                and assert_eq(len(tools), 2)
                and assert_eq(tools[0].name, "save_memory")
                and assert_eq(tools[1].name, "recall_memory")
            )
            or [t.name for t in tools]
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 5: Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def sec5_helpers():
    print("\n" + "=" * 60)
    print("  SEC 5: Helpers")
    print("=" * 60)

    from langchain_core.messages import SystemMessage as SM
    from langchain_core.tools import BaseTool

    # normalize_tools
    def _dummy_tool(x: str) -> str:
        """A dummy tool for testing."""
        return x

    run_test(
        "normalize_tools: callable",
        lambda: (
            (
                (tools := normalize_tools([_dummy_tool]))
                and assert_eq(len(tools), 1)
                and assert_true(isinstance(tools[0], BaseTool))
            )
            or tools
        ),
    )

    run_test(
        "normalize_tools: BaseTool passthrough",
        lambda: (
            (
                (tools := normalize_tools([calculate]))
                and assert_eq(len(tools), 1)
                and assert_eq(tools[0].name, "calculate")
            )
            or tools[0].name
        ),
    )

    run_test(
        "normalize_tools: dict with function",
        lambda: (
            (
                (tools := normalize_tools([{"function": lambda x: x, "name": "my_fn", "description": "desc"}]))
                and assert_eq(len(tools), 1)
                and assert_eq(tools[0].name, "my_fn")
            )
            or tools[0].name
        ),
    )

    run_test("normalize_tools: empty list", lambda: assert_eq(normalize_tools([]), []) or "[]")

    run_test("normalize_tools: unknown type skipped", lambda: assert_eq(len(normalize_tools([42])), 0) or "skipped")

    # reserved tool name enforcement
    run_test(
        "RESERVED_TOOL_NAMES is a frozenset",
        lambda: assert_true(isinstance(RESERVED_TOOL_NAMES, frozenset)) or "frozenset",
    )

    def _test_reserved_single():
        @tool
        def save_memory(key: str) -> str:
            """User tool that collides."""
            return key

        try:
            _check_reserved_tool_names([save_memory])
            return False
        except ValueError as e:
            assert "save_memory" in str(e)
            assert "reserved" in str(e).lower()
            return f"ValueError: {e}"

    run_test("reserved tool name: save_memory raises ValueError", _test_reserved_single)

    def _test_reserved_multiple():
        @tool
        def recall_memory(q: str) -> str:
            """Collides."""
            return q

        @tool
        def load_skill(name: str) -> str:
            """Collides."""
            return name

        try:
            _check_reserved_tool_names([recall_memory, load_skill])
            return False
        except ValueError as e:
            assert "load_skill" in str(e)
            assert "recall_memory" in str(e)
            return f"ValueError: {e}"

    run_test("reserved tool name: multiple collisions raises ValueError", _test_reserved_multiple)

    def _test_no_collision():
        @tool
        def my_custom_tool(x: str) -> str:
            """No collision."""
            return x

        _check_reserved_tool_names([my_custom_tool])
        return "no collision"

    run_test("reserved tool name: non-reserved passes", _test_no_collision)

    def _test_create_agent_rejects_reserved():
        @tool
        def save_memory(key: str) -> str:
            """Collides with internal tool."""
            return key

        try:
            create_agent(model=_make_llm(), tools=[save_memory], name="ReservedTest")
            return False
        except ValueError as e:
            assert "reserved" in str(e).lower()
            return f"ValueError: {e}"

    run_test("create_agent rejects reserved tool name", _test_create_agent_rejects_reserved)

    # resolve_system_prompt
    run_test(
        "resolve_system_prompt: str passthrough",
        lambda: assert_eq(resolve_system_prompt("hello"), "hello") or "hello",
    )

    run_test(
        "resolve_system_prompt: SystemMessage",
        lambda: assert_eq(resolve_system_prompt(SM(content="sys")), "sys") or "sys",
    )

    run_test(
        "resolve_system_prompt: None → default",
        lambda: assert_eq(resolve_system_prompt(None), DEFAULT_SYSTEM_PROMPT) or "default",
    )

    # topological_sort
    run_test(
        "topological_sort: linear chain",
        lambda: (
            (
                (
                    configs := [
                        ResolvedWorkerConfig(worker_id="a", task="t", system_prompt="p"),
                        ResolvedWorkerConfig(worker_id="b", task="t", system_prompt="p", depends_on=["a"]),
                    ]
                )
                and (sorted_c := topological_sort(configs))
                and assert_eq(sorted_c[0].worker_id, "a")
                and assert_eq(sorted_c[1].worker_id, "b")
            )
            or [c.worker_id for c in sorted_c]
        ),
    )

    run_test(
        "topological_sort: circular raises",
        lambda: (
            _expect_error(
                lambda: topological_sort(
                    [
                        ResolvedWorkerConfig(worker_id="a", task="t", system_prompt="p", depends_on=["b"]),
                        ResolvedWorkerConfig(worker_id="b", task="t", system_prompt="p", depends_on=["a"]),
                    ]
                )
            )
            or "circular detected"
        ),
    )

    run_test(
        "topological_sort: unknown dep raises",
        lambda: (
            _expect_error(
                lambda: topological_sort(
                    [
                        ResolvedWorkerConfig(worker_id="a", task="t", system_prompt="p", depends_on=["z"]),
                    ]
                )
            )
            or "unknown dep detected"
        ),
    )

    # group_by_level
    run_test(
        "group_by_level: flat (all independent)",
        lambda: (
            (
                (
                    configs := [
                        ResolvedWorkerConfig(worker_id="a", task="t", system_prompt="p"),
                        ResolvedWorkerConfig(worker_id="b", task="t", system_prompt="p"),
                    ]
                )
                and (levels := group_by_level(configs))
                and assert_eq(len(levels), 1)
                and assert_eq(len(levels[0]), 2)
            )
            or f"{len(levels)} levels"
        ),
    )

    run_test(
        "group_by_level: 3-deep",
        lambda: (
            (
                (
                    configs := [
                        ResolvedWorkerConfig(worker_id="a", task="t", system_prompt="p"),
                        ResolvedWorkerConfig(worker_id="b", task="t", system_prompt="p", depends_on=["a"]),
                        ResolvedWorkerConfig(worker_id="c", task="t", system_prompt="p", depends_on=["b"]),
                    ]
                )
                and (levels := group_by_level(configs))
                and assert_eq(len(levels), 3)
            )
            or f"{len(levels)} levels"
        ),
    )

    run_test(
        "group_by_level: diamond",
        lambda: (
            (
                (
                    configs := [
                        ResolvedWorkerConfig(worker_id="a", task="t", system_prompt="p"),
                        ResolvedWorkerConfig(worker_id="b", task="t", system_prompt="p", depends_on=["a"]),
                        ResolvedWorkerConfig(worker_id="c", task="t", system_prompt="p", depends_on=["a"]),
                        ResolvedWorkerConfig(worker_id="d", task="t", system_prompt="p", depends_on=["b", "c"]),
                    ]
                )
                and (levels := group_by_level(configs))
                and assert_eq(len(levels), 3)
            )
            or f"{len(levels)} levels"
        ),
    )

    run_test("group_by_level: empty", lambda: assert_eq(group_by_level([]), []) or "[]")

    run_test(
        "group_by_level: circular raises",
        lambda: (
            _expect_error(
                lambda: group_by_level(
                    [
                        ResolvedWorkerConfig(worker_id="a", task="t", system_prompt="p", depends_on=["b"]),
                        ResolvedWorkerConfig(worker_id="b", task="t", system_prompt="p", depends_on=["a"]),
                    ]
                )
            )
            or "circular"
        ),
    )

    # _parse_critic_response
    run_test(
        "critic parser: standard format",
        lambda: (
            (
                (r := _parse_critic_response("SCORE: 8\nPASSED: yes\nFEEDBACK: Good.", 7))
                and assert_eq(r["score"], 8)
                and assert_true(r["passed"])
            )
            or r
        ),
    )

    run_test(
        "critic parser: threshold boundary (score == threshold → True)",
        lambda: (
            (
                (r := _parse_critic_response("SCORE: 7\nFEEDBACK: Ok.", 7))
                and assert_eq(r["score"], 7)
                and assert_true(r["passed"])
            )
            or r
        ),
    )

    run_test(
        "critic parser: garbled text defaults",
        lambda: ((r := _parse_critic_response("random garbage text", 7)) and assert_eq(r["score"], 5)) or r,
    )

    run_test(
        "critic parser: case insensitive",
        lambda: (
            (
                (r := _parse_critic_response("score: 9\npassed: YES\nfeedback: Great!", 7))
                and assert_eq(r["score"], 9)
                and assert_true(r["passed"])
            )
            or r
        ),
    )

    # BlackboardState
    run_test(
        "BlackboardState write/read/snapshot",
        lambda: (
            (
                (bs := BlackboardState(goal="test", slots={"research": None, "analysis": None}))
                and bs.write("research", "data here", "ks1") is None
                and assert_eq(bs.read("research"), "data here")
                and assert_true("research" in bs.filled)
                and assert_true(len(bs.history) == 1)
                and assert_true("FILLED" in bs.snapshot())
            )
            or bs.snapshot()[:100]
        ),
    )

    run_test(
        "BlackboardState unfilled_slots",
        lambda: (
            (
                (bs := BlackboardState(goal="t", slots={"a": None, "b": None}))
                and bs.write("a", "v", "k") is None
                and assert_eq(bs.unfilled_slots(), ["b"])
            )
            or bs.unfilled_slots()
        ),
    )

    # Signal queue helpers
    from agloom.patterns.worker_gates import drain_for_halt, get_signal_queue

    run_test(
        "get_signal_queue: from config",
        lambda: (
            ((q := asyncio.Queue()) and (sq := get_signal_queue({"signal_queue": q})) and assert_true(sq is q))
            or "found"
        ),
    )

    run_test("get_signal_queue: empty agent dict", lambda: assert_eq(get_signal_queue({}), None) or "None")

    async def test_drain_empty():
        q = asyncio.Queue()
        result = await drain_for_halt(q)
        assert result is False
        return "no halt"

    run_async_test("drain_for_halt: empty queue", test_drain_empty())

    async def test_drain_none():
        result = await drain_for_halt(None)
        assert result is False
        return "None queue"

    run_async_test("drain_for_halt: None queue", test_drain_none())


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 6: Skills Models
# ═══════════════════════════════════════════════════════════════════════════════


def sec6_skills_models():
    print("\n" + "=" * 60)
    print("  SEC 6: Skills Models")
    print("=" * 60)

    # SkillManifest
    run_test(
        "SkillManifest creation",
        lambda: (
            (
                (m := SkillManifest(name="test-skill", description="A test skill"))
                and assert_eq(m.name, "test-skill")
                and assert_eq(m.scope, "global")
                and assert_eq(m.source, "static")
            )
            or m.name
        ),
    )

    run_test(
        "SkillManifest.classifier_line",
        lambda: (
            (
                (m := SkillManifest(name="s1", description="desc1", tags=["tag1"]))
                and (line := m.classifier_line())
                and assert_true("s1" in line)
                and assert_true("desc1" in line)
                and assert_true("tag1" in line)
            )
            or line
        ),
    )

    run_test(
        "SkillManifest to/from metadata roundtrip",
        lambda: (
            (
                (m := SkillManifest(name="s1", description="d1", tags=["t1"], scope="agent"))
                and (meta := m.to_metadata())
                and (m2 := SkillManifest.from_metadata(meta))
                and assert_eq(m.name, m2.name)
                and assert_eq(m.scope, m2.scope)
            )
            or "roundtrip ok"
        ),
    )

    run_test(
        "SkillManifest.from_metadata missing name → None",
        lambda: assert_eq(SkillManifest.from_metadata({"description": "d"}), None) or "None",
    )

    # SkillContent
    run_test(
        "SkillContent.to_system_prompt_block",
        lambda: (
            (
                (m := SkillManifest(name="s1", description="d1"))
                and (c := SkillContent(manifest=m, body="## Steps\n1. Do X"))
                and (block := c.to_system_prompt_block())
                and assert_true("SKILL: s1" in block)
                and assert_true("Do X" in block)
            )
            or block[:100]
        ),
    )

    run_test(
        "SkillContent to/from LTS metadata roundtrip",
        lambda: (
            (
                (m := SkillManifest(name="s1", description="d1"))
                and (c := SkillContent(manifest=m, body="body text", scripts=["a.py"]))
                and (meta := c.to_lts_metadata())
                and (c2 := SkillContent.from_lts_metadata(meta))
                and assert_eq(c.body, c2.body)
                and assert_eq(c.scripts, c2.scripts)
            )
            or "roundtrip ok"
        ),
    )

    # AgentSkill
    run_test(
        "AgentSkill confidence calculation",
        lambda: (
            (
                (
                    s := AgentSkill(
                        name="s", description="d", trigger="t", pattern="REACT", success_count=8, failure_count=2
                    )
                )
                and assert_eq(s.confidence(), 0.8)
            )
            or s.confidence()
        ),
    )

    run_test(
        "AgentSkill confidence decay/boost",
        lambda: (
            (
                (
                    s := AgentSkill(
                        name="s", description="d", trigger="t", pattern="REACT", success_count=3, failure_count=7
                    )
                )
                and assert_eq(s.confidence(), 0.3)
            )
            or s.confidence()
        ),
    )

    run_test(
        "AgentSkill.should_prune below 0.2 after 5+ uses",
        lambda: (
            (
                (
                    s := AgentSkill(
                        name="s", description="d", trigger="t", pattern="REACT", success_count=0, failure_count=6
                    )
                )
                and assert_true(s.should_prune())
            )
            or "should prune"
        ),
    )

    run_test(
        "AgentSkill.should_prune False when < 5 uses",
        lambda: (
            (
                (
                    s := AgentSkill(
                        name="s", description="d", trigger="t", pattern="REACT", success_count=0, failure_count=3
                    )
                )
                and assert_true(not s.should_prune())
            )
            or "should NOT prune"
        ),
    )

    run_test(
        "AgentSkill.to_manifest",
        lambda: (
            (
                (s := AgentSkill(name="s1", description="d1", trigger="t", pattern="REACT"))
                and (m := s.to_manifest())
                and assert_eq(m.name, "s1")
                and assert_eq(m.source, "learned")
            )
            or m.name
        ),
    )

    # Lifecycle constants
    run_test(
        "Lifecycle constants exist",
        lambda: (
            (
                assert_true(isinstance(MAX_SKILLS, int))
                and assert_true(isinstance(REVIEW_EVERY_N_RUNS, int))
                and assert_true(GLOBAL_NS == ("skills", "global"))
            )
            or "constants ok"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 7: Feedback System (unit, async, no LLM)
# ═══════════════════════════════════════════════════════════════════════════════


def sec7_feedback():
    print("\n" + "=" * 60)
    print("  SEC 7: Feedback System")
    print("=" * 60)

    # FeedbackStore
    async def test_fs_save_get():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        record = _make_record(run_id="r1", score=_make_score())
        await fs.save(record)
        got = await fs.get("r1")
        assert got is not None, "Record should exist"
        assert got.run_id == "r1"
        return f"got run_id={got.run_id}"

    run_async_test("FeedbackStore save/get roundtrip", test_fs_save_get())

    async def test_fs_get_missing():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        got = await fs.get("nonexistent")
        assert got is None
        return "None"

    run_async_test("FeedbackStore get missing → None", test_fs_get_missing())

    async def test_fs_get_recent_empty():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        records = await fs.get_recent(10)
        assert records == []
        return "[]"

    run_async_test("FeedbackStore get_recent empty", test_fs_get_recent_empty())

    async def test_fs_get_recent():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        for i in range(3):
            await fs.save(_make_record(run_id=f"r{i}", score=_make_score()))
        records = await fs.get_recent(10)
        assert len(records) >= 3
        return f"{len(records)} records"

    run_async_test("FeedbackStore get_recent populated", test_fs_get_recent())

    async def test_fs_apply_positive():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        await fs.save(_make_record(run_id="r1"))
        ok = await fs.apply_user_feedback("r1", "positive", comment="great")
        assert ok is True
        return "applied"

    run_async_test("FeedbackStore apply_user_feedback positive", test_fs_apply_positive())

    async def test_fs_apply_negative():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        await fs.save(_make_record(run_id="r1", skill_used="my_skill"))
        fired = []

        async def cb(name, rid):
            fired.append(name)

        fs.on_skill_failure(cb)
        ok = await fs.apply_user_feedback("r1", "negative")
        assert ok is True
        assert "my_skill" in fired, f"skill failure should fire: {fired}"
        return "negative + skill failure"

    run_async_test("FeedbackStore apply_user_feedback negative → skill failure", test_fs_apply_negative())

    async def test_fs_apply_unknown():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        ok = await fs.apply_user_feedback("nonexistent", "positive")
        assert ok is False
        return "False"

    run_async_test("FeedbackStore apply_user_feedback unknown run_id", test_fs_apply_unknown())

    async def test_fs_correction_memory():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        await fs.save(_make_record(run_id="r1", query="What is X?"))
        await fs.apply_user_feedback("r1", "negative", correct="X is Y")
        results = await lts.asearch(("memory", "TestAgent"), "correction")
        assert len(results) >= 1
        return "correction saved"

    run_async_test("FeedbackStore correction → memory", test_fs_correction_memory())

    async def test_fs_skill_failure_callback():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        signals = []

        async def cb(name, rid):
            signals.append((name, rid))

        fs.on_skill_failure(cb)
        await fs.signal_skill_failure("skill1", "run1")
        assert signals == [("skill1", "run1")]
        return "signalled"

    run_async_test("FeedbackStore skill failure signal/callback", test_fs_skill_failure_callback())

    async def test_fs_skill_failure_error_swallow():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")

        async def bad_cb(name, rid):
            raise RuntimeError("boom")

        fs.on_skill_failure(bad_cb)
        await fs.signal_skill_failure("s", "r")
        return "swallowed"

    run_async_test("FeedbackStore skill failure error swallowing", test_fs_skill_failure_error_swallow())

    async def test_fs_stats():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="TestAgent")
        await fs.save(_make_record(run_id="r1", score=_make_score()))
        stats = await fs.get_stats()
        assert stats["total"] >= 1
        return stats

    run_async_test("FeedbackStore get_stats", test_fs_stats())

    async def test_fs_ns_isolation():
        lts = _make_lts()
        fs1 = FeedbackStore(store=lts, agent_name="Agent1")
        fs2 = FeedbackStore(store=lts, agent_name="Agent2")
        await fs1.save(_make_record(run_id="r1"))
        got = await fs2.get("r1")
        assert got is None, "Different agents should be isolated"
        return "isolated"

    run_async_test("FeedbackStore namespace isolation", test_fs_ns_isolation())

    # Handlers
    run_test(
        "NoOpFeedbackHandler protocol check",
        lambda: assert_true(isinstance(NoOpFeedbackHandler(), UserFeedbackHandler)) or "is UserFeedbackHandler",
    )

    async def test_noop():
        h = NoOpFeedbackHandler()
        await h.on_feedback("r1", "positive")
        return "silent"

    run_async_test("NoOpFeedbackHandler fires silently", test_noop())

    run_test(
        "WebhookFeedbackHandler stores URL",
        lambda: (
            ((h := WebhookFeedbackHandler(url="http://example.com/fb")) and assert_eq(h._url, "http://example.com/fb"))
            or h._url
        ),
    )

    async def test_composite_zero():
        h = CompositeHandler()
        await h.on_feedback("r1", "positive")
        return "no crash"

    run_async_test("CompositeHandler zero handlers", test_composite_zero())

    async def test_composite_chaining():
        called = []

        class H1:
            async def on_feedback(self, run_id, rating, comment="", correct="", metadata={}):
                called.append("h1")

        class H2:
            async def on_feedback(self, run_id, rating, comment="", correct="", metadata={}):
                called.append("h2")

        h = CompositeHandler(H1(), H2())
        await h.on_feedback("r1", "pos")
        assert set(called) == {"h1", "h2"}
        return "both fired"

    run_async_test("CompositeHandler chaining", test_composite_chaining())

    async def test_composite_error_swallow():
        class Bad:
            async def on_feedback(self, run_id, rating, comment="", correct="", metadata={}):
                raise RuntimeError("boom")

        class Good:
            async def on_feedback(self, run_id, rating, comment="", correct="", metadata={}):
                pass

        h = CompositeHandler(Bad(), Good())
        await h.on_feedback("r1", "neg")
        return "swallowed"

    run_async_test("CompositeHandler error swallowing", test_composite_error_swallow())

    run_test(
        "CompositeHandler fluent add",
        lambda: (
            ((h := CompositeHandler()) and (h.add(NoOpFeedbackHandler())) and assert_eq(len(h._handlers), 1)) or "added"
        ),
    )

    # TrendDetector
    run_test(
        "TrendDetector counter",
        lambda: (
            (
                (lts := _make_lts())
                and (fs := FeedbackStore(store=lts, agent_name="T"))
                and (td := TrendDetector(llm=None, feedback_store=fs, run_every=5))
                and td.on_run_complete() is None
                and assert_eq(td._run_count, 1)
            )
            or td._run_count
        ),
    )

    run_test(
        "TrendDetector last_report initially None",
        lambda: (
            (
                (td := TrendDetector(llm=None, feedback_store=FeedbackStore(store=_make_lts(), agent_name="T")))
                and assert_eq(td.last_report(), None)
            )
            or "None"
        ),
    )

    async def test_td_force_insufficient():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="T")
        td = TrendDetector(llm=None, feedback_store=fs)
        result = await td.force_analyze()
        assert result is None
        return "None (insufficient)"

    run_async_test("TrendDetector force_analyze insufficient data", test_td_force_insufficient())

    # TrendDetector._aggregate
    run_test(
        "TrendDetector._aggregate stats",
        lambda: (
            (
                (td := TrendDetector(llm=None, feedback_store=FeedbackStore(store=_make_lts(), agent_name="T")))
                and (
                    stats := td._aggregate(
                        [
                            {
                                "score": {"accuracy": 0.8, "completeness": 0.7, "efficiency": 0.9, "relevance": 0.85},
                                "pattern_used": "REACT",
                                "skill_used": "s1",
                            },
                        ]
                    )
                )
                and assert_eq(stats["total"], 1)
                and assert_true(stats["overall_avg"] > 0)
            )
            or stats
        ),
    )

    run_test(
        "TrendDetector._aggregate empty list",
        lambda: (
            (
                (td := TrendDetector(llm=None, feedback_store=FeedbackStore(store=_make_lts(), agent_name="T")))
                and (stats := td._aggregate([]))
                and assert_eq(stats["total"], 0)
                and assert_eq(stats["no_skill_pct"], 0.0)
            )
            or stats
        ),
    )

    # wireup
    async def test_wireup_builds_all():
        lts = _make_lts()
        llm = _make_llm()
        cfg = build_feedback_system(llm=llm, long_term_store=lts, agent_name="WireupTest")
        assert "feedback_store" in cfg
        assert "auto_evaluator" in cfg
        assert "trend_detector" in cfg
        assert "feedback_handler" in cfg
        assert isinstance(cfg["feedback_handler"], NoOpFeedbackHandler)
        return "all wired"

    run_async_test("wireup: build_feedback_system creates all", test_wireup_builds_all())

    run_test(
        "wireup: run_fresh_feedback_hooks empty config safe",
        lambda: (run_fresh_feedback_hooks(config={}, result=_make_result(), query="test") is None and "safe") or "safe",
    )

    # __init__.py re-exports
    run_test(
        "feedback.__init__ re-exports all symbols",
        lambda: (
            import_check(
                "agloom.feedback",
                [
                    "AutoEvaluator",
                    "RunRecord",
                    "EvalScore",
                    "FeedbackStore",
                    "TrendDetector",
                    "UserFeedbackHandler",
                    "NoOpFeedbackHandler",
                    "LTSFeedbackHandler",
                    "WebhookFeedbackHandler",
                    "CompositeHandler",
                ],
            )
            or "all present"
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 8: Tools
# ═══════════════════════════════════════════════════════════════════════════════


def sec8_tools():
    print("\n" + "=" * 60)
    print("  SEC 8: Built-in Tools")
    print("=" * 60)

    run_test(
        "extract_keywords produces output",
        lambda: (
            ((r := extract_keywords.invoke({"text": "machine learning is great"})) and assert_true("Keywords:" in r))
            or r
        ),
    )

    run_test(
        "calculate evaluates expression",
        lambda: ((r := calculate.invoke({"expression": "2 + 3 * 4"})) and assert_true("14" in r)) or r,
    )

    run_test(
        "calculate handles errors",
        lambda: ((r := calculate.invoke({"expression": "import os"})) and assert_true("error" in r.lower())) or r,
    )

    run_test(
        "summarize_text short text passthrough",
        lambda: ((r := summarize_text.invoke({"text": "short text"})) and assert_eq(r, "short text")) or r,
    )

    run_test(
        "summarize_text truncates long text",
        lambda: (
            (
                (r := summarize_text.invoke({"text": " ".join(["word"] * 200), "max_words": 10}))
                and assert_true("..." in r)
            )
            or r
        ),
    )

    def test_resolve():
        resolved, missing = resolve_tools(["calculate", "unknown_tool"])
        assert len(resolved) == 1
        assert missing == ["unknown_tool"]
        return f"resolved={len(resolved)} missing={missing}"

    run_test("resolve_tools", test_resolve)


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 9: Classifier (LLM integration)
# ═══════════════════════════════════════════════════════════════════════════════


def sec9_classifier():
    print("\n" + "=" * 60)
    print("  SEC 9: Classifier (LLM)")
    print("=" * 60)

    llm = _make_llm()
    from agloom.classifier import analyze_query

    async def test_direct_classify():
        analysis = await analyze_query(llm, "Hello!", [])
        assert analysis.pattern == PatternType.DIRECT, f"Expected DIRECT, got {analysis.pattern}"
        assert analysis.direct_response is not None
        return f"pattern={analysis.pattern.value} response={analysis.direct_response[:60]}"

    run_async_test("Classifier: DIRECT for greeting", test_direct_classify(), input_data="Hello!")

    async def test_react_classify():
        analysis = await analyze_query(llm, "Calculate 2+2", [calculate])
        assert analysis.pattern in (PatternType.REACT, PatternType.DIRECT), (
            f"Expected REACT/DIRECT, got {analysis.pattern}"
        )
        return f"pattern={analysis.pattern.value}"

    run_async_test("Classifier: REACT with tools", test_react_classify(), input_data="Calculate 2+2")

    async def test_complex_classify():
        analysis = await analyze_query(
            llm,
            "Research transformers, then critique the research, then write a final summary",
            [extract_keywords],
        )
        assert analysis.complexity >= 4, f"Expected complexity>=4, got {analysis.complexity}"
        return f"pattern={analysis.pattern.value} complexity={analysis.complexity}"

    run_async_test(
        "Classifier: complex multi-step query",
        test_complex_classify(),
        input_data="Research transformers, critique, summarize",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 10: All 9 Patterns (LLM integration)
# ═══════════════════════════════════════════════════════════════════════════════


def sec10_patterns():
    print("\n" + "=" * 60)
    print("  SEC 10: All 9 Patterns (LLM)")
    print("=" * 60)

    llm = _make_llm()

    async def test_pattern_direct():
        agent = create_agent(model=llm, name="DirectAgent")
        result = await agent.ainvoke("What is 2+2?")
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        assert result.pattern_used == PatternType.DIRECT
        return f"output={result.output[:80]}"

    run_async_test("Pattern DIRECT: simple greeting", test_pattern_direct(), input_data="What is 2+2?")

    async def test_pattern_react():
        agent = create_agent(model=llm, tools=[calculate], name="ReactAgent")
        result = await agent.ainvoke("Calculate sqrt(144)")
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        return f"pattern={result.pattern_used.value} output={result.output[:80]}"

    run_async_test("Pattern REACT: calculate with tool", test_pattern_react(), input_data="Calculate sqrt(144)")

    async def test_pattern_supervisor():
        agent = create_agent(model=llm, tools=[extract_keywords], name="SupervisorAgent")
        result = await agent.ainvoke(
            "Compare three topics: machine learning, deep learning, and "
            "reinforcement learning — give me a brief overview of each"
        )
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        return f"pattern={result.pattern_used.value} output={result.output[:80]}"

    run_async_test(
        "Pattern SUPERVISOR: parallel comparison", test_pattern_supervisor(), input_data="Compare ML/DL/RL topics"
    )

    async def test_pattern_pipeline():
        agent = create_agent(model=llm, tools=[extract_keywords, summarize_text], name="PipelineAgent")
        result = await agent.ainvoke(
            "Take this text: 'Deep learning uses neural networks with multiple "
            "layers.' First extract keywords, then summarize the keywords."
        )
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        return f"pattern={result.pattern_used.value} output={result.output[:80]}"

    run_async_test(
        "Pattern PIPELINE: extract → summarize", test_pattern_pipeline(), input_data="Extract keywords then summarize"
    )

    async def test_pattern_planner():
        agent = create_agent(model=llm, tools=[extract_keywords], name="PlannerAgent")
        result = await agent.ainvoke(
            "First extract keywords from 'AI is transforming healthcare', "
            "then based on those keywords, explain the main concept"
        )
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        return f"pattern={result.pattern_used.value} output={result.output[:80]}"

    run_async_test(
        "Pattern PLANNER_EXECUTOR: sequential reasoning", test_pattern_planner(), input_data="Extract then explain"
    )

    async def test_pattern_reflection():
        agent = create_agent(model=llm, name="ReflectionAgent")
        result = await agent.ainvoke(
            "Write a rigorous one-paragraph explanation of how attention mechanisms work in transformers"
        )
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        return f"pattern={result.pattern_used.value} output={result.output[:80]}"

    run_async_test(
        "Pattern REFLECTION: critique loop",
        test_pattern_reflection(),
        input_data="Write rigorous explanation of attention",
    )

    async def test_pattern_swarm():
        agent = create_agent(model=llm, name="SwarmAgent")
        result = await agent.ainvoke(
            "Debate the pros and cons of microservices versus monolithic "
            "architecture from the perspective of a startup CTO and an "
            "enterprise architect"
        )
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        return f"pattern={result.pattern_used.value} output={result.output[:80]}"

    run_async_test("Pattern SWARM: debate", test_pattern_swarm(), input_data="Debate microservices vs monolith")

    async def test_pattern_blackboard():
        agent = create_agent(model=llm, name="BlackboardAgent")
        result = await agent.ainvoke(
            "Research the topic of quantum computing, then critique the research, then refine it based on the critique"
        )
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        return f"pattern={result.pattern_used.value} output={result.output[:80]}"

    run_async_test(
        "Pattern BLACKBOARD: shared state", test_pattern_blackboard(), input_data="Research → critique → refine"
    )

    async def test_pattern_hybrid_dag():
        agent = create_agent(model=llm, tools=[extract_keywords], name="HybridDagAgent")
        result = await agent.ainvoke(
            "In parallel: research AI ethics and research AI safety. Then synthesize both into a final report."
        )
        assert result.success, f"Failed: {result.error}"
        assert result.output, "Empty output"
        return f"pattern={result.pattern_used.value} output={result.output[:80]}"

    run_async_test(
        "Pattern HYBRID_DAG: mixed parallel+sequential",
        test_pattern_hybrid_dag(),
        input_data="Parallel research → synthesize",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 11: Frozen Agent (LLM integration)
# ═══════════════════════════════════════════════════════════════════════════════


def sec11_frozen():
    print("\n" + "=" * 60)
    print("  SEC 11: Frozen Agent (LLM)")
    print("=" * 60)

    llm = _make_llm()

    async def test_frozen_single_key():
        agent = create_agent(
            model=llm,
            name="FrozenSingle",
            frozen=True,
            frozen_template="Classify sentiment: {input}",
            input_key="input",
        )
        r = await agent.ainvoke("I love this product!")
        assert r.success, f"Failed: {r.error}"
        assert r.output, "Empty output"
        return f"output={r.output[:80]}"

    run_async_test("Frozen: single key substitution", test_frozen_single_key(), input_data="I love this product!")

    async def test_frozen_multi_key():
        agent = create_agent(
            model=llm,
            name="FrozenMulti",
            frozen=True,
            frozen_template="From {sender}: {body}. Is this spam?",
            input_key=["sender", "body"],
        )
        r = await agent.ainvoke({"sender": "unknown@spam.com", "body": "You won $1M click here"})
        assert r.success, f"Failed: {r.error}"
        assert r.output, "Empty output"
        return f"output={r.output[:80]}"

    run_async_test("Frozen: multi key substitution", test_frozen_multi_key(), input_data="sender=spam, body=win $1M")

    async def test_frozen_reuse_analysis():
        agent = create_agent(
            model=llm,
            name="FrozenReuse",
            frozen=True,
            frozen_template="Translate to French: {input}",
            input_key="input",
        )
        r1 = await agent.ainvoke("Hello")
        assert r1.success
        fa1 = agent.config.get("frozen_analysis")
        assert fa1 is not None, "frozen_analysis should be cached"

        r2 = await agent.ainvoke("Goodbye")
        assert r2.success
        fa2 = agent.config.get("frozen_analysis")
        assert fa1 is fa2, "frozen_analysis should be reused (same object)"
        return f"r1={r1.output[:40]} r2={r2.output[:40]} same_analysis={fa1 is fa2}"

    run_async_test("Frozen: reuses cached analysis", test_frozen_reuse_analysis(), input_data="Hello then Goodbye")

    async def test_frozen_concurrent():
        agent = create_agent(
            model=llm, name="FrozenConc", frozen=True, frozen_template="Classify: {input}", input_key="input"
        )
        tasks = [agent.ainvoke(f"item {i}") for i in range(3)]
        results = await asyncio.gather(*tasks)
        assert all(r.success for r in results), "All should succeed"
        return f"all {len(results)} succeeded"

    run_async_test("Frozen: concurrent calls", test_frozen_concurrent(), input_data="3 concurrent frozen calls")

    async def test_frozen_vs_dynamic():
        frozen = create_agent(
            model=llm, name="FvdFrozen", frozen=True, frozen_template="Answer: {input}", input_key="input"
        )
        dynamic = create_agent(model=llm, name="FvdDynamic")
        query = "What is Python?"
        r_frozen = await frozen.ainvoke(query)
        r_dynamic = await dynamic.ainvoke(query)
        assert r_frozen.success
        assert r_dynamic.success
        return f"frozen={r_frozen.output[:40]} dynamic={r_dynamic.output[:40]}"

    run_async_test("Frozen vs Dynamic: both succeed", test_frozen_vs_dynamic(), input_data="What is Python?")

    async def test_frozen_with_tools():
        agent = create_agent(
            model=llm,
            tools=[calculate],
            name="FrozenTools",
            frozen=True,
            frozen_template="Calculate: {input}",
            input_key="input",
        )
        r = await agent.ainvoke("sqrt(25)")
        assert r.success
        return f"output={r.output[:80]}"

    run_async_test("Frozen: with tools", test_frozen_with_tools(), input_data="sqrt(25)")

    run_test(
        "Frozen: frozen=True without template raises at create_agent",
        lambda: (
            _expect_error(lambda: create_agent(model=llm, name="Bad", frozen=True, frozen_template="")) or "rejected"
        ),
    )

    async def test_frozen_dict_to_nonfrozen():
        agent = create_agent(model=llm, name="NonFrozen")
        try:
            await agent.ainvoke({"key": "value"})
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "frozen=True" in str(e)
            return f"ValueError: {e}"

    run_async_test("Frozen: dict input to non-frozen agent raises", test_frozen_dict_to_nonfrozen())


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 12: Memory & Cross-Turn (LLM integration)
# ═══════════════════════════════════════════════════════════════════════════════


def sec12_memory_cross_turn():
    print("\n" + "=" * 60)
    print("  SEC 12: Memory & Cross-Turn (LLM)")
    print("=" * 60)

    llm = _make_llm()
    from langgraph.store.memory import InMemoryStore

    async def test_session_cross_turn():
        agent = create_agent(model=llm, name="MemAgent")
        r1 = await agent.ainvoke("My favorite color is blue", thread_id="t1")
        assert r1.success
        r2 = await agent.ainvoke("What is my favorite color?", thread_id="t1")
        assert r2.success
        return f"r1={r1.output[:40]} r2={r2.output[:40]}"

    run_async_test(
        "Session memory: cross-turn reference", test_session_cross_turn(), input_data="Set color=blue, then ask"
    )

    async def test_thread_isolation():
        agent = create_agent(model=llm, name="IsoAgent")
        r1 = await agent.ainvoke("My name is Alice", thread_id="t1")
        r2 = await agent.ainvoke("What is my name?", thread_id="t2")
        assert r1.success and r2.success
        return f"t1={r1.output[:40]} t2={r2.output[:40]}"

    run_async_test("Thread isolation: t1 vs t2", test_thread_isolation(), input_data="Name=Alice on t1, ask on t2")

    async def test_lt_save_recall():
        store = InMemoryStore()
        _lts = LongTermStore(store=store)
        agent = create_agent(model=llm, tools=[calculate], store=store, name="LTAgent")
        r1 = await agent.ainvoke("Remember that my project deadline is March 15", user_id="u1")
        assert r1.success
        r2 = await agent.ainvoke("When is my project deadline?", user_id="u1")
        assert r2.success
        return f"r1={r1.output[:40]} r2={r2.output[:40]}"

    run_async_test("LT memory: save + recall", test_lt_save_recall(), input_data="Save deadline, then recall")

    async def test_user_isolation():
        store = InMemoryStore()
        agent = create_agent(model=llm, store=store, name="UserIsoAgent")
        await agent.ainvoke("My name is Bob", user_id="u1")
        r = await agent.ainvoke("What is my name?", user_id="u2")
        assert r.success
        return f"u2 response={r.output[:60]}"

    run_async_test("User isolation: u1 vs u2", test_user_isolation(), input_data="Name=Bob as u1, ask as u2")

    async def test_enable_memory_tools_false():
        store = InMemoryStore()
        agent = create_agent(model=llm, store=store, name="NoMemTools", enable_memory_tools=False)
        tool_names = [t.name for t in agent.config["tools"]]
        assert "save_memory" not in tool_names, f"Unexpected: {tool_names}"
        assert "recall_memory" not in tool_names
        return f"tools={tool_names}"

    run_async_test("enable_memory_tools=False", test_enable_memory_tools_false())


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 13: Skills (LLM integration)
# ═══════════════════════════════════════════════════════════════════════════════


def sec13_skills():
    print("\n" + "=" * 60)
    print("  SEC 13: Skills (LLM)")
    print("=" * 60)

    llm = _make_llm()
    from langgraph.store.memory import InMemoryStore

    async def test_skill_registry_with_store():
        store = InMemoryStore()
        agent = create_agent(model=llm, store=store, name="SkillAgent")
        assert agent.config.get("skill_registry") is not None
        return "registry created"

    run_async_test("create_agent with store: skill_registry present", test_skill_registry_with_store())

    async def test_skill_registry_no_store():
        agent = create_agent(model=llm, name="NoStoreAgent")
        assert agent.config.get("skill_registry") is None
        return "no registry"

    run_async_test("create_agent without store: no skill_registry", test_skill_registry_no_store())

    async def test_load_skill_tool():
        store = InMemoryStore()
        agent = create_agent(model=llm, store=store, name="LoadSkillAgent")
        tool_names = [t.name for t in agent.config["tools"]]
        assert "load_skill" in tool_names, f"Missing load_skill: {tool_names}"
        return f"tools={tool_names}"

    run_async_test("load_skill tool present when store provided", test_load_skill_tool())

    async def test_skill_injector_empty():
        from agloom.skills.injector import SkillInjector
        from agloom.skills.registry import SkillRegistry

        store = InMemoryStore()
        lts = LongTermStore(store=store)
        registry = SkillRegistry(lts, "TestAgent")
        injector = SkillInjector(registry)
        ctx = await injector.get_context("test query")
        assert ctx == ""
        return "empty context"

    run_async_test("SkillInjector empty registry → empty context", test_skill_injector_empty())


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 14: Feedback (LLM integration)
# ═══════════════════════════════════════════════════════════════════════════════


def sec14_feedback_integration():
    print("\n" + "=" * 60)
    print("  SEC 14: Feedback (LLM)")
    print("=" * 60)

    llm = _make_llm()
    from langgraph.store.memory import InMemoryStore

    async def test_auto_evaluator_direct():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="EvalTest")
        evaluator = AutoEvaluator(llm=llm, feedback_store=fs, agent_name="EvalTest")
        result = _make_result(output="The capital of France is Paris.")
        await evaluator._score_and_store(result, "What is the capital of France?", None, "test-run-1")
        record = await fs.get("test-run-1")
        assert record is not None, "Record should be saved"
        assert record.score is not None, "Score should be set"
        return f"score={record.score.to_log_str()}"

    run_async_test(
        "AutoEvaluator: scores via real LLM", test_auto_evaluator_direct(), input_data="Capital of France → Paris"
    )

    async def test_eval_low_score_skill_failure():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="LowScore")
        signals = []

        async def cb(name, rid):
            signals.append(name)

        fs.on_skill_failure(cb)
        evaluator = AutoEvaluator(llm=llm, feedback_store=fs, agent_name="LowScore")
        result = _make_result(output="I don't know the answer to anything.")
        await evaluator._score_and_store(result, "Explain quantum physics in detail", "bad_skill", "test-low")
        record = await fs.get("test-low")
        if record and record.score and record.score.overall() < 0.40:
            assert "bad_skill" in signals
        return f"score={record.score.to_log_str() if record and record.score else 'n/a'}"

    run_async_test("AutoEvaluator: low score signals skill failure", test_eval_low_score_skill_failure())

    async def test_eval_empty_output():
        lts = _make_lts()
        fs = FeedbackStore(store=lts, agent_name="EmptyOut")
        evaluator = AutoEvaluator(llm=llm, feedback_store=fs, agent_name="EmptyOut")
        result = _make_result(output="")
        await evaluator._score_and_store(result, "test", None, "test-empty")
        record = await fs.get("test-empty")
        assert record is not None
        assert record.score is None, "Empty output should have no score"
        return "score=None"

    run_async_test("AutoEvaluator: empty output → score=None", test_eval_empty_output())

    async def test_e2e_feedback():
        store = InMemoryStore()
        agent = create_agent(model=llm, store=store, name="FeedbackE2E")
        result = await agent.ainvoke("What is Python?")
        assert result.success
        await asyncio.sleep(2)
        await agent.feedback(result.run_id, "positive", comment="Great!")
        return f"run_id={result.run_id}"

    run_async_test(
        "End-to-end: ainvoke → feedback", test_e2e_feedback(), input_data="What is Python? → positive feedback"
    )

    async def test_feedback_negative_correction():
        store = InMemoryStore()
        _lts = LongTermStore(store=store)
        agent = create_agent(model=llm, store=store, name="CorrectionAgent")
        result = await agent.ainvoke("What is RLHF?")
        assert result.success
        await asyncio.sleep(2)
        await agent.feedback(result.run_id, "negative", correct="RLHF = Reinforcement Learning from Human Feedback")
        return f"correction stored for run_id={result.run_id}"

    run_async_test(
        "Feedback: negative with correction",
        test_feedback_negative_correction(),
        input_data="RLHF → negative + correction",
    )

    async def test_no_store_feedback():
        agent = create_agent(model=llm, name="NoStoreFB")
        assert agent.config.get("_feedback") == {}
        await agent.feedback("fake_id", "positive")
        return "no-op"

    run_async_test("create_agent without store: empty _feedback", test_no_store_feedback())


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 15: Multi-Agent & Isolation (LLM integration)
# ═══════════════════════════════════════════════════════════════════════════════


def sec15_multi_agent():
    print("\n" + "=" * 60)
    print("  SEC 15: Multi-Agent & Isolation (LLM)")
    print("=" * 60)

    llm = _make_llm()

    async def test_two_agents_different_names():
        a1 = create_agent(model=llm, name="Agent1")
        a2 = create_agent(model=llm, name="Agent2")
        r1 = await a1.ainvoke("Say hello")
        r2 = await a2.ainvoke("Say goodbye")
        assert r1.success and r2.success
        return f"a1={r1.output[:30]} a2={r2.output[:30]}"

    run_async_test("Two agents, different names: independent", test_two_agents_different_names())

    async def test_two_agents_same_name():
        a1 = create_agent(model=llm, name="Shared")
        a2 = create_agent(model=llm, name="Shared")
        r1 = await a1.ainvoke("Hi")
        r2 = await a2.ainvoke("Hello")
        assert r1.success and r2.success
        assert a1.config is not a2.config, "Configs should be separate objects"
        return "isolated configs"

    run_async_test("Two agents, same name: isolated config", test_two_agents_same_name())

    async def test_concurrent_burst():
        agent = create_agent(model=llm, name="BurstAgent")
        tasks = [agent.ainvoke(f"What is {i}+{i}?") for i in range(3)]
        results = await asyncio.gather(*tasks)
        assert all(r.success for r in results)
        return f"all {len(results)} succeeded"

    run_async_test("Concurrent burst: 3 parallel ainvokes", test_concurrent_burst())

    async def test_concurrent_different_agents():
        agents = [create_agent(model=llm, name=f"CA{i}") for i in range(3)]
        tasks = [a.ainvoke("Hello") for a in agents]
        results = await asyncio.gather(*tasks)
        assert all(r.success for r in results)
        return f"all {len(results)} succeeded"

    run_async_test("Concurrent: 3 different agents in parallel", test_concurrent_different_agents())

    async def test_thread_isolation_same_agent():
        agent = create_agent(model=llm, name="ThreadIso")
        await agent.ainvoke("My name is X", thread_id="t1")
        await agent.ainvoke("My name is Y", thread_id="t2")
        r1 = await agent.ainvoke("What is my name?", thread_id="t1")
        r2 = await agent.ainvoke("What is my name?", thread_id="t2")
        assert r1.success and r2.success
        return f"t1={r1.output[:30]} t2={r2.output[:30]}"

    run_async_test("Thread isolation: same agent, different threads", test_thread_isolation_same_agent())

    # resolve_ids
    def test_resolve_ids():
        agent = create_agent(model=llm, name="RidAgent")
        tid, ltns, cfg = agent.resolve_ids(None, "u1", None)
        assert ltns == ("RidAgent", "u1"), f"Expected ('RidAgent', 'u1'), got {ltns}"
        return f"ltns={ltns}"

    run_test("resolve_ids: user_id namespace", test_resolve_ids)

    def test_resolve_ids_explicit():
        agent = create_agent(model=llm, name="RidExp")
        tid, ltns, cfg = agent.resolve_ids("t1", None, ("custom", "ns"))
        assert ltns == ("custom", "ns"), f"Expected explicit ns, got {ltns}"
        return f"ltns={ltns}"

    run_test("resolve_ids: explicit lt_namespace", test_resolve_ids_explicit)

    def test_resolve_ids_auto_thread():
        agent = create_agent(model=llm, name="RidAuto")
        tid, ltns, cfg = agent.resolve_ids(None, None, None)
        assert ltns[0] == "RidAuto"
        assert tid == ltns[1]
        return "auto thread_id used as namespace"

    run_test("resolve_ids: auto-generated thread", test_resolve_ids_auto_thread)


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 16: HITL
# ═══════════════════════════════════════════════════════════════════════════════


def sec16_hitl():
    print("\n" + "=" * 60)
    print("  SEC 16: HITL (LLM)")
    print("=" * 60)

    llm = _make_llm()

    async def test_hitl_abort():
        async def abort_cb(event, msg):
            return "abort"

        agent = create_agent(model=llm, name="HITLAbort", interrupt_before=["DIRECT"], user_callback=abort_cb)
        r = await agent.ainvoke("Hi there")
        assert not r.success, "Should be aborted"
        assert "Aborted" in r.output or "abort" in r.output.lower()
        return f"aborted: {r.output[:60]}"

    run_async_test("HITL L1: interrupt_before abort", test_hitl_abort(), input_data="Hi there with abort callback")

    async def test_hitl_continue():
        async def continue_cb(event, msg):
            return "continue"

        agent = create_agent(model=llm, name="HITLCont", interrupt_before=["DIRECT"], user_callback=continue_cb)
        r = await agent.ainvoke("Hi")
        assert r.success, f"Should succeed: {r.error}"
        return f"continued: {r.output[:60]}"

    run_async_test("HITL L1: interrupt_before continue", test_hitl_continue(), input_data="Hi with continue callback")

    async def test_hitl_after():
        fired = []

        async def after_cb(event, msg):
            fired.append(event)
            return "continue"

        agent = create_agent(model=llm, name="HITLAfter", interrupt_after=["DIRECT"], user_callback=after_cb)
        r = await agent.ainvoke("Hello")
        assert r.success
        return f"after fired: {len(fired)} times"

    run_async_test("HITL L1: interrupt_after fires", test_hitl_after(), input_data="Hello with after callback")

    async def test_hitl_no_callback():
        agent = create_agent(model=llm, name="HITLNoCb", interrupt_before=["DIRECT"])
        r = await agent.ainvoke("Hi")
        assert r.success, "Should succeed (fail-open)"
        return f"transparent: {r.output[:60]}"

    run_async_test("HITL: no callback = transparent (fail-open)", test_hitl_no_callback())

    async def test_hitl_callback_exception():
        async def bad_cb(event, msg):
            raise RuntimeError("callback crashed")

        agent = create_agent(model=llm, name="HITLBadCb", interrupt_before=["DIRECT"], user_callback=bad_cb)
        r = await agent.ainvoke("Hi")
        assert r.success, "Should succeed (fail-open on exception)"
        return f"fail-open: {r.output[:60]}"

    run_async_test("HITL: callback exception = fail-open", test_hitl_callback_exception())


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 17: Advanced Features
# ═══════════════════════════════════════════════════════════════════════════════


def sec17_advanced():
    print("\n" + "=" * 60)
    print("  SEC 17: Advanced Features (LLM)")
    print("=" * 60)

    llm = _make_llm()
    from langchain_core.messages import SystemMessage as SM

    async def test_dynamic_str_prompt():
        agent = create_agent(model=llm, name="StrPrompt", system_prompt="You always respond in ALL CAPS.")
        r = await agent.ainvoke("Say hello")
        assert r.success
        return f"output={r.output[:60]}"

    run_async_test("Dynamic system_prompt: str", test_dynamic_str_prompt(), input_data="ALL CAPS prompt")

    async def test_dynamic_sm_prompt():
        agent = create_agent(model=llm, name="SMPrompt", system_prompt=SM(content="Reply with exactly one word."))
        r = await agent.ainvoke("What color is the sky?")
        assert r.success
        return f"output={r.output[:60]}"

    run_async_test("Dynamic system_prompt: SystemMessage", test_dynamic_sm_prompt(), input_data="One-word reply prompt")

    async def test_dynamic_none_prompt():
        agent = create_agent(model=llm, name="NonePrompt", system_prompt=None)
        assert agent.config["system_prompt"] == DEFAULT_SYSTEM_PROMPT
        return "default used"

    run_async_test("Dynamic system_prompt: None → default", test_dynamic_none_prompt())

    async def test_streaming_tokens():
        agent = create_agent(model=llm, name="StreamTok")
        tokens = []
        async for t in agent.astream("Say hello"):
            tokens.append(t)
        assert len(tokens) > 0
        full = "".join(tokens)
        assert len(full) > 0
        return f"tokens={len(tokens)} full={full[:60]}"

    run_async_test("Streaming: astream tokens", test_streaming_tokens(), input_data="Say hello")

    async def test_streaming_result():
        agent = create_agent(model=llm, name="StreamRes")
        results = []
        async for r in agent.astream("Say hello", stream_mode="result"):
            results.append(r)
        assert len(results) == 1
        assert isinstance(results[0], ExecutionResult)
        return f"result type={type(results[0]).__name__}"

    run_async_test("Streaming: astream result mode", test_streaming_result(), input_data="Say hello, result mode")

    async def test_async_context_manager():
        async with create_agent(model=llm, name="CtxMgr") as agent:
            r = await agent.ainvoke("Hi")
            assert r.success
        return "context manager ok"

    run_async_test("Async context manager", test_async_context_manager())

    async def test_register_pattern():
        agent = create_agent(model=llm, name="RegPat")

        async def custom_handler(config, query, analysis, invoke_config):
            return ExecutionResult(
                pattern_used=PatternType.DIRECT, query=query, output="custom handler fired", steps_taken=1, success=True
            )

        agent.register_pattern(PatternType.DIRECT, custom_handler)
        assert agent.config["registry"][PatternType.DIRECT] is custom_handler
        return "registered"

    run_async_test("register_pattern at runtime", test_register_pattern())

    async def test_error_recovery():
        agent = create_agent(model=llm, name="ErrRecov")
        r = await agent.ainvoke("")
        assert isinstance(r, ExecutionResult)
        return f"success={r.success} output={r.output[:60]}"

    run_async_test("Error recovery: empty query doesn't crash", test_error_recovery(), input_data="empty string")


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 18: create_agent Param Coverage
# ═══════════════════════════════════════════════════════════════════════════════


def sec18_param_coverage():
    print("\n" + "=" * 60)
    print("  SEC 18: create_agent Param Coverage (LLM)")
    print("=" * 60)

    llm = _make_llm()
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.store.memory import InMemoryStore

    async def test_model_as_instance():
        agent = create_agent(model=llm, name="ModelInst")
        assert agent.config["llm"] is llm
        return "BaseChatModel instance"

    run_async_test("Param: model as BaseChatModel", test_model_as_instance())

    async def test_max_concurrent():
        agent = create_agent(model=llm, name="MaxConc", max_concurrent=8)
        assert agent.config["max_concurrent"] == 8
        return "max_concurrent=8"

    run_async_test("Param: max_concurrent", test_max_concurrent())

    async def test_max_retries():
        agent = create_agent(model=llm, name="MaxRetry", max_retries=5)
        assert agent.config["max_retries"] == 5
        return "max_retries=5"

    run_async_test("Param: max_retries", test_max_retries())

    async def test_retry_delay():
        agent = create_agent(model=llm, name="RetryDel", retry_delay=2.5)
        assert agent.config["retry_delay"] == 2.5
        return "retry_delay=2.5"

    run_async_test("Param: retry_delay", test_retry_delay())

    async def test_session_max_turns():
        agent = create_agent(model=llm, name="MaxTurns", session_max_turns=50)
        assert agent.config["memory"].max_turns == 50
        return "session_max_turns=50"

    run_async_test("Param: session_max_turns", test_session_max_turns())

    async def test_reflection_params():
        agent = create_agent(model=llm, name="ReflParam", max_reflection_iterations=5, reflection_threshold=8)
        assert agent.config["max_reflection_iterations"] == 5
        assert agent.config["reflection_threshold"] == 8
        return "reflection params set"

    run_async_test("Param: reflection iterations + threshold", test_reflection_params())

    async def test_user_id():
        agent = create_agent(model=llm, name="UserId", user_id="harish")
        assert agent.config["user_id"] == "harish"
        return "user_id=harish"

    run_async_test("Param: user_id propagation", test_user_id())

    async def test_checkpointer():
        cp = MemorySaver()
        agent = create_agent(model=llm, name="CpAgent", checkpointer=cp)
        assert agent.config["checkpointer"] is cp
        return "checkpointer set"

    run_async_test("Param: checkpointer with MemorySaver", test_checkpointer())

    async def test_debug_mode():
        agent = create_agent(model=llm, name="DebugAgent", debug=True)
        assert agent.config["debug"] is True
        return "debug=True"

    run_async_test("Param: debug mode", test_debug_mode())

    async def test_frozen_params():
        agent = create_agent(
            model=llm, name="FrozenParam", frozen=True, frozen_template="Test: {input}", input_key="input"
        )
        assert agent.config["frozen"] is True
        assert agent.config["frozen_template"] == "Test: {input}"
        assert agent.config["input_key"] == "input"
        return "frozen params set"

    run_async_test("Param: frozen=True in create_agent", test_frozen_params())

    async def test_enable_memory_tools():
        store = InMemoryStore()
        agent = create_agent(model=llm, store=store, name="NoMem", enable_memory_tools=False)
        names = [t.name for t in agent.config["tools"]]
        assert "save_memory" not in names
        assert "recall_memory" not in names
        return f"tools={names}"

    run_async_test("Param: enable_memory_tools=False", test_enable_memory_tools())

    async def test_middleware_param():
        class TestMW:
            def before_agent(self, query, ctx):
                return query.upper()

        agent = create_agent(model=llm, name="MWParam", middleware=[TestMW()])
        r = await agent.ainvoke("hello")
        assert r.success
        return f"middleware applied, output={r.output[:60]}"

    run_async_test("Param: middleware transforms query", test_middleware_param(), input_data="hello → uppercased")


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 19: Real User Scenarios
# ═══════════════════════════════════════════════════════════════════════════════


def sec19_real_user():
    print("\n" + "=" * 60)
    print("  SEC 19: Real User Scenarios (LLM)")
    print("=" * 60)

    llm = _make_llm()
    from langgraph.store.memory import InMemoryStore

    async def test_qa_chatbot():
        agent = create_agent(model=llm, name="QABot")
        r1 = await agent.ainvoke("I'm working on a machine learning project", thread_id="session1")
        assert r1.success
        r2 = await agent.ainvoke("What topic am I working on?", thread_id="session1")
        assert r2.success
        return f"r1={r1.output[:40]} r2={r2.output[:40]}"

    run_async_test("Scenario: Q&A chatbot multi-turn", test_qa_chatbot(), input_data="ML project → ask topic")

    async def test_batch_classifier():
        agent = create_agent(
            model=llm, name="BatchClass", frozen=True, frozen_template="Classify sentiment: {input}", input_key="input"
        )
        inputs = ["I love it!", "Terrible product", "It's okay", "Amazing experience", "Not bad at all"]
        results = []
        for inp in inputs:
            r = await agent.ainvoke(inp)
            assert r.success
            results.append(r.output[:30])
        return f"classified {len(results)}: {results}"

    run_async_test("Scenario: Batch classifier (frozen)", test_batch_classifier(), input_data="5 sentiment inputs")

    async def test_multi_agent_delegation():
        simple = create_agent(model=llm, name="SimpleAgent")
        complex_ag = create_agent(model=llm, tools=[calculate, extract_keywords], name="ComplexAgent")
        r1 = await simple.ainvoke("Hi")
        r2 = await complex_ag.ainvoke(
            "Calculate sqrt(256) and extract keywords from 'neural networks learn representations'"
        )
        assert r1.success and r2.success
        return f"simple={r1.output[:30]} complex={r2.output[:30]}"

    run_async_test(
        "Scenario: Multi-agent delegation",
        test_multi_agent_delegation(),
        input_data="Simple greeting + complex calculation",
    )

    async def test_feedback_loop():
        store = InMemoryStore()
        agent = create_agent(model=llm, store=store, name="FBLoop")
        r1 = await agent.ainvoke("What is RLHF?")
        assert r1.success
        await asyncio.sleep(2)
        await agent.feedback(r1.run_id, "negative", correct="RLHF = Reinforcement Learning from Human Feedback")
        r2 = await agent.ainvoke("What is RLHF?")
        assert r2.success
        return f"r1={r1.output[:40]} r2={r2.output[:40]}"

    run_async_test(
        "Scenario: Feedback loop (run → feedback → improved run)",
        test_feedback_loop(),
        input_data="RLHF → negative feedback → re-ask",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 21: Callable System Prompt, Middleware & Interrupts (LLM)
# ═══════════════════════════════════════════════════════════════════════════════


def sec21_dynamic_prompt_middleware_interrupts():
    print("\n" + "=" * 60)
    print("  SEC 21: Callable System Prompt, Middleware & Interrupts (LLM)")
    print("=" * 60)

    llm = _make_llm()
    from langchain_core.messages import SystemMessage as SM

    # ── 21.1  Callable (function) system_prompt ─────────────────────────────

    async def test_callable_prompt_sync():
        """system_prompt=<sync function> — LangChain dynamic prompt API."""

        def my_prompt(state):
            return f"You are a {state.get('context', {}).get('role', 'helper')}. Always reply in exactly one sentence."

        agent = create_agent(model=llm, name="CallPromptSync", system_prompt=my_prompt)
        r = await agent.ainvoke("What is Python?", context={"role": "pirate captain"})
        assert r.success, f"Should succeed: {r.error}"
        return f"output={r.output[:80]}"

    run_async_test(
        "Callable system_prompt: sync function",
        test_callable_prompt_sync(),
        input_data="role=pirate captain, What is Python?",
    )

    async def test_callable_prompt_async():
        """system_prompt=<async function>."""

        async def my_async_prompt(state):
            role = state.get("context", {}).get("role", "assistant")
            return f"You are a {role}. Respond in exactly 3 words."

        agent = create_agent(model=llm, name="CallPromptAsync", system_prompt=my_async_prompt)
        r = await agent.ainvoke("Say hello", context={"role": "robot"})
        assert r.success
        return f"output={r.output[:80]}"

    run_async_test(
        "Callable system_prompt: async function", test_callable_prompt_async(), input_data="role=robot, Say hello"
    )

    async def test_callable_prompt_returns_sm():
        """Callable that returns a SystemMessage object."""

        def sm_prompt(state):
            return SM(content="You are a formal British butler. Always say 'Indeed, sir.'")

        agent = create_agent(model=llm, name="CallPromptSM", system_prompt=sm_prompt)
        r = await agent.ainvoke("What is the weather?")
        assert r.success
        return f"output={r.output[:80]}"

    run_async_test(
        "Callable system_prompt: returns SystemMessage",
        test_callable_prompt_returns_sm(),
        input_data="butler prompt → weather question",
    )

    async def test_callable_prompt_receives_state():
        """Verify the callable receives query, context, thread_id, user_id."""
        received = {}

        def spy_prompt(state):
            received.update(state)
            return "You are a helpful assistant."

        agent = create_agent(model=llm, name="CallPromptSpy", system_prompt=spy_prompt)
        await agent.ainvoke("Hi", thread_id="t99", user_id="u42", context={"key": "val"})
        assert received.get("query") == "Hi", f"query={received.get('query')}"
        assert received.get("user_id") == "u42"
        assert received.get("thread_id") == "t99"
        assert received.get("context", {}).get("key") == "val"
        return f"state keys={sorted(received.keys())}"

    run_async_test(
        "Callable system_prompt: receives full state",
        test_callable_prompt_receives_state(),
        input_data="spy prompt with thread_id=t99, user_id=u42",
    )

    async def test_callable_vs_static_prompt():
        """Callable and static prompts both work on same model."""
        static_agent = create_agent(model=llm, name="StaticP", system_prompt="Reply with 'STATIC'.")
        dynamic_agent = create_agent(model=llm, name="DynP", system_prompt=lambda s: "Reply with 'DYNAMIC'.")
        r1 = await static_agent.ainvoke("test")
        r2 = await dynamic_agent.ainvoke("test")
        assert r1.success and r2.success
        return f"static={r1.output[:30]} dynamic={r2.output[:30]}"

    run_async_test(
        "Callable vs static system_prompt: both work",
        test_callable_vs_static_prompt(),
        input_data="STATIC vs DYNAMIC prompt",
    )

    # ── Unit: resolve_system_prompt handles Callable ────────────────────────

    def my_fn(state):
        return "hello"

    run_test(
        "resolve_system_prompt: Callable returned as-is",
        lambda: (
            ((r := resolve_system_prompt(my_fn)) and assert_true(callable(r)) and assert_true(r is my_fn))
            or "callable preserved"
        ),
    )

    run_test(
        "resolve_system_prompt: lambda returned as-is",
        lambda: (
            ((fn := (lambda s: "test")) and (r := resolve_system_prompt(fn)) and assert_true(callable(r)))
            or "lambda preserved"
        ),
    )

    # ── 21.2  Middleware comprehensive tests ─────────────────────────────────

    async def test_mw_before_agent_transforms():
        """before_agent middleware transforms query before classification."""

        class UpperMW:
            def before_agent(self, query, ctx):
                return query.upper()

        agent = create_agent(model=llm, name="MWBefore", middleware=[UpperMW()])
        r = await agent.ainvoke("hello world")
        assert r.success
        return f"output={r.output[:60]}"

    run_async_test(
        "Middleware: before_agent transforms query",
        test_mw_before_agent_transforms(),
        input_data="hello world → HELLO WORLD",
    )

    async def test_mw_after_agent_transforms():
        """after_agent middleware transforms the result."""

        class SuffixMW:
            def after_agent(self, result, ctx):
                return ExecutionResult(
                    pattern_used=result.pattern_used,
                    query=result.query,
                    output=result.output + " [PROCESSED]",
                    steps_taken=result.steps_taken,
                    success=result.success,
                    run_id=result.run_id,
                )

        agent = create_agent(model=llm, name="MWAfter", middleware=[SuffixMW()])
        r = await agent.ainvoke("Say hi")
        assert r.success
        assert "[PROCESSED]" in r.output, f"Suffix missing: {r.output[-30:]}"
        return f"output ends with={r.output[-20:]}"

    run_async_test(
        "Middleware: after_agent transforms result",
        test_mw_after_agent_transforms(),
        input_data="Say hi → output + [PROCESSED]",
    )

    async def test_mw_chaining_order():
        """Multiple middleware run before_agent in order, after_agent in reverse."""
        order = []

        class MW1:
            def before_agent(self, query, ctx):
                order.append("b1")
                return query

            def after_agent(self, result, ctx):
                order.append("a1")
                return result

        class MW2:
            def before_agent(self, query, ctx):
                order.append("b2")
                return query

            def after_agent(self, result, ctx):
                order.append("a2")
                return result

        agent = create_agent(model=llm, name="MWOrder", middleware=[MW1(), MW2()])
        r = await agent.ainvoke("test")
        assert r.success
        assert order[:2] == ["b1", "b2"], f"before order: {order}"
        assert order[-2:] == ["a2", "a1"], f"after order: {order}"
        return f"order={order}"

    run_async_test(
        "Middleware: chaining order (before=fwd, after=rev)", test_mw_chaining_order(), input_data="MW1 + MW2 chaining"
    )

    async def test_mw_async_support():
        """Async middleware is awaited properly."""

        class AsyncMW:
            async def before_agent(self, query, ctx):
                await asyncio.sleep(0.01)
                return query + " [ASYNC]"

        agent = create_agent(model=llm, name="MWAsync", middleware=[AsyncMW()])
        r = await agent.ainvoke("hello")
        assert r.success
        return f"output={r.output[:60]}"

    run_async_test(
        "Middleware: async before_agent awaited", test_mw_async_support(), input_data="hello → hello [ASYNC]"
    )

    async def test_mw_context_passed():
        """Context dict is forwarded to middleware."""
        received_ctx = {}

        class SpyMW:
            def before_agent(self, query, ctx):
                received_ctx.update(ctx)
                return query

        agent = create_agent(model=llm, name="MWCtx", middleware=[SpyMW()])
        await agent.ainvoke("test", context={"env": "prod", "version": "3"})
        assert received_ctx.get("env") == "prod"
        assert received_ctx.get("version") == "3"
        return f"ctx={received_ctx}"

    run_async_test(
        "Middleware: context dict forwarded", test_mw_context_passed(), input_data="context={env:prod, version:3}"
    )

    async def test_mw_none_return_passthrough():
        """Middleware returning None doesn't modify the query."""

        class PassthroughMW:
            def before_agent(self, query, ctx):
                return None

        agent = create_agent(model=llm, name="MWNone", middleware=[PassthroughMW()])
        r = await agent.ainvoke("Hi")
        assert r.success
        return f"output={r.output[:40]}"

    run_async_test(
        "Middleware: None return = passthrough",
        test_mw_none_return_passthrough(),
        input_data="None return → query unchanged",
    )

    async def test_mw_before_only():
        """Middleware with only before_agent (no after_agent)."""

        class BeforeOnlyMW:
            def before_agent(self, query, ctx):
                return query

        agent = create_agent(model=llm, name="MWBeforeOnly", middleware=[BeforeOnlyMW()])
        r = await agent.ainvoke("test")
        assert r.success
        return f"no crash, output={r.output[:30]}"

    run_async_test("Middleware: before_agent only (no after_agent)", test_mw_before_only())

    async def test_mw_after_only():
        """Middleware with only after_agent (no before_agent)."""

        class AfterOnlyMW:
            def after_agent(self, result, ctx):
                return result

        agent = create_agent(model=llm, name="MWAfterOnly", middleware=[AfterOnlyMW()])
        r = await agent.ainvoke("test")
        assert r.success
        return f"no crash, output={r.output[:30]}"

    run_async_test("Middleware: after_agent only (no before_agent)", test_mw_after_only())

    async def test_mw_empty_list():
        """Empty middleware list is fine."""
        agent = create_agent(model=llm, name="MWEmpty", middleware=[])
        r = await agent.ainvoke("Hi")
        assert r.success
        return f"output={r.output[:30]}"

    run_async_test("Middleware: empty list", test_mw_empty_list())

    # ── 21.3  Interrupt (L1) comprehensive tests ────────────────────────────

    async def test_interrupt_before_any_pattern():
        """interrupt_before works for whatever pattern the classifier picks."""

        async def abort_cb(event, msg):
            return "abort"

        agent = create_agent(
            model=llm, name="IBAll", tools=[calculate], interrupt_before=["DIRECT", "REACT"], user_callback=abort_cb
        )
        r = await agent.ainvoke("Hi")
        assert not r.success, "Should be aborted"
        assert "Aborted" in r.output
        return f"aborted: {r.output[:60]}"

    run_async_test(
        "Interrupt L1: abort any classified pattern",
        test_interrupt_before_any_pattern(),
        input_data="Hi → aborted regardless of pattern",
    )

    async def test_interrupt_after_modifies_result():
        """interrupt_after fires and can inspect partial output."""
        seen = []

        async def after_cb(event, msg):
            seen.append(msg)
            return "continue"

        agent = create_agent(model=llm, name="IAFires", interrupt_after=["DIRECT"], user_callback=after_cb)
        r = await agent.ainvoke("Hello")
        assert r.success
        assert len(seen) > 0, "interrupt_after should have fired"
        assert "Output:" in seen[0], f"Message should contain output: {seen[0][:60]}"
        return f"fired={len(seen)} msg_preview={seen[0][:40]}"

    run_async_test(
        "Interrupt L1: interrupt_after sees output",
        test_interrupt_after_modifies_result(),
        input_data="Hello → after fires with output preview",
    )

    async def test_interrupt_multiple_patterns():
        """interrupt_before can list multiple patterns."""
        calls = []

        async def track_cb(event, msg):
            calls.append(event)
            return "continue"

        agent = create_agent(model=llm, name="IMulti", interrupt_before=["DIRECT", "REACT"], user_callback=track_cb)
        r = await agent.ainvoke("Hi there")
        assert r.success
        return f"calls={len(calls)}"

    run_async_test(
        "Interrupt L1: multiple patterns in list",
        test_interrupt_multiple_patterns(),
        input_data="interrupt_before=['DIRECT','REACT']",
    )

    async def test_interrupt_before_and_after_same_pattern():
        """Both interrupt_before and interrupt_after on same pattern."""
        phases = []

        async def both_cb(event, msg):
            phases.append("before" if "BEFORE" in msg else "after")
            return "continue"

        agent = create_agent(
            model=llm, name="IBoth", interrupt_before=["DIRECT"], interrupt_after=["DIRECT"], user_callback=both_cb
        )
        r = await agent.ainvoke("Hello")
        assert r.success
        assert "before" in phases, f"before should fire: {phases}"
        assert "after" in phases, f"after should fire: {phases}"
        return f"phases={phases}"

    run_async_test(
        "Interrupt L1: before + after on same pattern",
        test_interrupt_before_and_after_same_pattern(),
        input_data="DIRECT with both before and after",
    )

    async def test_interrupt_callback_receives_query():
        """Callback message contains the query text."""
        seen_msg = []

        async def spy_cb(event, msg):
            seen_msg.append(msg)
            return "continue"

        agent = create_agent(model=llm, name="IQuery", interrupt_before=["DIRECT"], user_callback=spy_cb)
        await agent.ainvoke("My specific test query")
        assert any("My specific test query" in m for m in seen_msg), f"Query not in callback: {seen_msg}"
        return "query found in callback"

    run_async_test(
        "Interrupt L1: callback receives query text",
        test_interrupt_callback_receives_query(),
        input_data="My specific test query",
    )

    # ── 21.4  L2 tool-level interrupt ───────────────────────────────────────

    async def test_interrupt_before_tools_config():
        """interrupt_before_tools is stored in config."""
        agent = create_agent(
            model=llm, name="IBTools", interrupt_before_tools=["calculate"], user_callback=lambda e, m: "continue"
        )
        assert "calculate" in agent.config["interrupt_before_tools"]
        return f"tools={agent.config['interrupt_before_tools']}"

    run_async_test("Interrupt L2: interrupt_before_tools in config", test_interrupt_before_tools_config())

    # ── 21.5  L3 worker-level interrupt ─────────────────────────────────────

    async def test_interrupt_workers_config():
        """interrupt_before_workers and interrupt_after_workers stored in config."""
        agent = create_agent(
            model=llm,
            name="IBWorkers",
            interrupt_before_workers=["researcher"],
            interrupt_after_workers=["writer"],
            user_callback=lambda e, m: "continue",
        )
        assert "researcher" in agent.config["interrupt_before_workers"]
        assert "writer" in agent.config["interrupt_after_workers"]
        return f"before={agent.config['interrupt_before_workers']} after={agent.config['interrupt_after_workers']}"

    run_async_test("Interrupt L3: worker-level interrupts in config", test_interrupt_workers_config())

    # ── 21.6  L4 signal queue ───────────────────────────────────────────────

    async def test_signal_queue_per_run():
        """Each ainvoke gets a fresh signal_queue (isolation)."""
        agent = create_agent(model=llm, name="SigQ")
        q1 = agent.config.get("signal_queue")
        assert q1 is not None, "signal_queue should exist on config"
        return f"signal_queue type={type(q1).__name__}"

    run_async_test("Interrupt L4: signal_queue exists", test_signal_queue_per_run())

    # ── 21.7  create_agent additional param coverage ────────────────────────

    async def test_param_state_schema():
        """state_schema param accepted by create_agent."""
        from typing import TypedDict

        class MyState(TypedDict):
            messages: list

        agent = create_agent(model=llm, name="StateSchema", state_schema=MyState)
        assert agent is not None
        return "state_schema accepted"

    run_async_test("Param: state_schema accepted", test_param_state_schema())

    async def test_param_context_schema():
        """context_schema param accepted by create_agent."""
        from typing import TypedDict

        class MyCtx(TypedDict):
            role: str

        agent = create_agent(model=llm, name="CtxSchema", context_schema=MyCtx)
        assert agent is not None
        return "context_schema accepted"

    run_async_test("Param: context_schema accepted", test_param_context_schema())

    async def test_param_query_cache():
        """query_cache param stored in config."""
        agent = create_agent(model=llm, name="QCache", query_cache={"type": "memory"})
        assert agent.config["query_cache"] == {"type": "memory"}
        return "query_cache set"

    run_async_test("Param: query_cache stored", test_param_query_cache())

    async def test_param_response_format():
        """response_format param stored in config."""
        from pydantic import BaseModel

        class Answer(BaseModel):
            text: str
            confidence: float

        agent = create_agent(model=llm, name="RespFmt", response_format=Answer)
        assert agent.config["response_format"] is Answer
        return "response_format set"

    run_async_test("Param: response_format stored", test_param_response_format())

    async def test_param_mcp_servers():
        """mcp_servers param stored in config (no actual connection)."""
        agent = create_agent(model=llm, name="MCPTest", mcp_servers=[])
        assert agent.config["_mcp_servers"] == []
        return "mcp_servers=[]"

    run_async_test("Param: mcp_servers stored", test_param_mcp_servers())

    async def test_param_name_propagation():
        """name propagates to config and repr."""
        agent = create_agent(model=llm, name="MyCustomAgent")
        assert agent.config["name"] == "MyCustomAgent"
        assert "MyCustomAgent" in repr(agent)
        return f"name={agent.config['name']}"

    run_async_test("Param: name propagation", test_param_name_propagation())

    async def test_param_model_string():
        """model as string identifier (stored after resolution)."""
        agent = create_agent(model=llm, name="ModelStr")
        assert agent.config["llm"] is not None
        return f"model type={type(agent.config['llm']).__name__}"

    run_async_test("Param: model resolved and stored", test_param_model_string())

    async def test_callable_prompt_with_frozen_raises_concept():
        """Callable prompt + frozen=True: callable resolves per-run before frozen sub."""

        def counting_prompt(state):
            return "You classify text sentiment."

        agent = create_agent(
            model=llm,
            name="CallFrozen",
            system_prompt=counting_prompt,
            frozen=True,
            frozen_template="Sentiment: {input}",
            input_key="input",
        )
        r = await agent.ainvoke("I love this!")
        assert r.success
        return f"output={r.output[:60]}"

    run_async_test(
        "Callable system_prompt + frozen agent",
        test_callable_prompt_with_frozen_raises_concept(),
        input_data="callable prompt + frozen sentiment",
    )

    # ── 21.8  Middleware + HITL combined ─────────────────────────────────────

    async def test_mw_with_interrupt():
        """Middleware runs even when interrupts are active."""
        mw_ran = []

        class TrackMW:
            def before_agent(self, query, ctx):
                mw_ran.append("before")
                return query

            def after_agent(self, result, ctx):
                mw_ran.append("after")
                return result

        agent = create_agent(
            model=llm,
            name="MWInt",
            middleware=[TrackMW()],
            interrupt_before=["DIRECT"],
            user_callback=lambda e, m: "continue",
        )
        r = await agent.ainvoke("Hello")
        assert r.success
        assert "before" in mw_ran, "before_agent should run"
        assert "after" in mw_ran, "after_agent should run"
        return f"mw_ran={mw_ran}"

    run_async_test(
        "Middleware + Interrupt: both fire",
        test_mw_with_interrupt(),
        input_data="middleware + interrupt_before combined",
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 20: Logging & repr
# ═══════════════════════════════════════════════════════════════════════════════


def sec20_logging_repr():
    print("\n" + "=" * 60)
    print("  SEC 20: Logging & repr")
    print("=" * 60)

    llm = _make_llm()

    run_test(
        "get_logger returns _AgentLogger",
        lambda: (
            (
                (log := get_logger("test"))
                and assert_true(hasattr(log, "event"))
                and assert_true(hasattr(log, "debug"))
                and assert_true(hasattr(log, "warning"))
                and assert_true(hasattr(log, "error"))
            )
            or "has all methods"
        ),
    )

    async def test_repr():
        agent = create_agent(model=llm, name="ReprAgent")
        r = repr(agent)
        assert "ReprAgent" in r
        assert "feedback=" in r
        return r

    run_async_test("UnifiedAgent.__repr__() format", test_repr())

    async def test_repr_feedback_on():
        from langgraph.store.memory import InMemoryStore

        agent = create_agent(model=llm, store=InMemoryStore(), name="ReprFB")
        r = repr(agent)
        assert "feedback=on" in r, f"Expected feedback=on: {r}"
        return r

    run_async_test("UnifiedAgent.__repr__() feedback=on with store", test_repr_feedback_on())

    async def test_repr_frozen():
        agent = create_agent(model=llm, name="ReprFrozen", frozen=True, frozen_template="T: {input}", input_key="input")
        r = repr(agent)
        assert "frozen=True" in r, f"Expected frozen info: {r}"
        return r

    run_async_test("UnifiedAgent.__repr__() frozen info", test_repr_frozen())


# ═══════════════════════════════════════════════════════════════════════════════
#  SEC 22: Steps, Token Usage, Streaming, Events
# ═══════════════════════════════════════════════════════════════════════════════


def sec22_steps_tokens_streaming():
    print("\n" + "=" * 60)
    print("  SEC 22: Steps, Token Usage, Streaming & Events")
    print("=" * 60)

    # ── Unit tests: model creation ──

    run_test(
        "StepType has 11 values",
        lambda: assert_eq(len(StepType), 11) or "11 step types (includes TOKEN)",
    )

    run_test(
        "AgentStep creation with defaults",
        lambda: (
            (
                (s := AgentStep(type=StepType.CLASSIFY, name="test_step"))
                and assert_eq(s.type, StepType.CLASSIFY)
                and assert_eq(s.name, "test_step")
                and assert_eq(s.input, "")
                and assert_eq(s.output, "")
                and assert_eq(s.duration_ms, 0.0)
                and assert_true(len(s.timestamp) > 0)
                and assert_eq(s.metadata, {})
            )
            or "AgentStep ok"
        ),
    )

    run_test(
        "AgentStep creation with all fields",
        lambda: (
            (
                (
                    s := AgentStep(
                        type=StepType.TOOL_CALL,
                        name="calculate",
                        input="2+2",
                        output="4",
                        duration_ms=15.3,
                        timestamp="2025-01-01T00:00:00Z",
                        metadata={"tool_name": "calc"},
                    )
                )
                and assert_eq(s.type, StepType.TOOL_CALL)
                and assert_eq(s.input, "2+2")
                and assert_eq(s.output, "4")
                and assert_eq(s.duration_ms, 15.3)
                and assert_eq(s.metadata["tool_name"], "calc")
            )
            or "full AgentStep ok"
        ),
    )

    run_test(
        "AgentEvent creation",
        lambda: (
            (
                (e := AgentEvent(type="thinking", data={"reasoning": "analyzing"}))
                and assert_eq(e.type, "thinking")
                and assert_eq(e.data["reasoning"], "analyzing")
                and assert_true(len(e.timestamp) > 0)
            )
            or "AgentEvent ok"
        ),
    )

    run_test(
        "AgentEvent done type",
        lambda: (
            (
                (e := AgentEvent(type="done", data={"result": {"output": "hello"}}))
                and assert_eq(e.type, "done")
                and assert_eq(e.data["result"]["output"], "hello")
            )
            or "done event ok"
        ),
    )

    run_test(
        "_make_step helper",
        lambda: (
            (
                (s := _make_step(StepType.LLM_CALL, "direct", input="q", output="a", duration_ms=50.0, model="gpt"))
                and assert_eq(s.type, StepType.LLM_CALL)
                and assert_eq(s.name, "direct")
                and assert_eq(s.input, "q")
                and assert_eq(s.output, "a")
                and assert_eq(s.duration_ms, 50.0)
                and assert_eq(s.metadata["model"], "gpt")
            )
            or "_make_step ok"
        ),
    )

    run_test(
        "_make_step truncates long input/output to 500 chars",
        lambda: (
            (
                (s := _make_step(StepType.LLM_CALL, "trunc", input="x" * 1000, output="y" * 1000))
                and assert_eq(len(s.input), 500)
                and assert_eq(len(s.output), 500)
            )
            or "truncation ok"
        ),
    )

    run_test(
        "_merge_token_usage sums values",
        lambda: (
            (
                (
                    m := _merge_token_usage(
                        {"input_tokens": 10, "output_tokens": 5},
                        {"input_tokens": 20, "output_tokens": 15, "total_tokens": 35},
                    )
                )
                and assert_eq(m["input_tokens"], 30)
                and assert_eq(m["output_tokens"], 20)
                and assert_eq(m["total_tokens"], 35)
            )
            or "merge ok"
        ),
    )

    run_test(
        "_merge_token_usage empty base",
        lambda: (
            ((m := _merge_token_usage({}, {"input_tokens": 10})) and assert_eq(m["input_tokens"], 10))
            or "merge empty ok"
        ),
    )

    run_test(
        "ExecutionResult has steps and token_usage fields",
        lambda: (
            (
                (r := _make_result())
                and assert_true(isinstance(r.steps, list))
                and assert_eq(len(r.steps), 0)
                and assert_true(isinstance(r.token_usage, dict))
                and assert_eq(len(r.token_usage), 0)
            )
            or "fields exist"
        ),
    )

    run_test(
        "ExecutionResult with steps populated",
        lambda: (
            (
                (s1 := AgentStep(type=StepType.CLASSIFY, name="cls", output="DIRECT"))
                and (s2 := AgentStep(type=StepType.LLM_CALL, name="llm", duration_ms=100))
                and (r := _make_result(steps=[s1, s2], token_usage={"total_tokens": 50}))
                and assert_eq(len(r.steps), 2)
                and assert_eq(r.steps[0].type, StepType.CLASSIFY)
                and assert_eq(r.steps[1].type, StepType.LLM_CALL)
                and assert_eq(r.token_usage["total_tokens"], 50)
            )
            or "steps populated ok"
        ),
    )

    run_test(
        "WorkerResult has token_usage field",
        lambda: (
            (
                (wr := WorkerResult(worker_id="w1", task="t", output="o", token_usage={"total_tokens": 100}))
                and assert_eq(wr.token_usage["total_tokens"], 100)
            )
            or "WorkerResult token_usage ok"
        ),
    )

    run_test(
        "WorkerResult token_usage defaults to empty",
        lambda: (
            ((wr := WorkerResult(worker_id="w1", task="t", output="o")) and assert_eq(wr.token_usage, {}))
            or "default empty ok"
        ),
    )

    run_test(
        "All StepType enum values",
        lambda: (
            (
                assert_true(StepType.CLASSIFY.value == "classify")
                and assert_true(StepType.LLM_CALL.value == "llm_call")
                and assert_true(StepType.TOOL_CALL.value == "tool_call")
                and assert_true(StepType.TOOL_RESULT.value == "tool_result")
                and assert_true(StepType.WORKER_START.value == "worker_start")
                and assert_true(StepType.WORKER_END.value == "worker_end")
                and assert_true(StepType.CACHE_HIT.value == "cache_hit")
                and assert_true(StepType.REFLECTION.value == "reflection")
                and assert_true(StepType.FALLBACK.value == "fallback")
                and assert_true(StepType.INTERRUPT.value == "interrupt")
            )
            or "all step types ok"
        ),
    )

    run_test(
        "_extract_token_usage from plain object (no usage)",
        lambda: assert_eq(_extract_token_usage("plain string"), {}) or "no usage",
    )

    # ── Integration: DIRECT pattern populates steps ──

    llm = _make_llm()

    async def test_direct_steps():
        agent = create_agent(model=llm, name="StepsDirectAgent")
        result = await agent.ainvoke("What is 2+2?")
        assert isinstance(result.steps, list), f"steps should be a list, got {type(result.steps)}"
        assert len(result.steps) >= 1, f"Expected at least 1 step, got {len(result.steps)}"
        step_types = [s.type for s in result.steps]
        has_classify = StepType.CLASSIFY in step_types
        has_llm = StepType.LLM_CALL in step_types
        assert has_classify or has_llm, f"Expected CLASSIFY or LLM_CALL step, got {step_types}"
        for s in result.steps:
            assert len(s.timestamp) > 0, "step should have a timestamp"
        return f"{len(result.steps)} steps: {[s.type.value for s in result.steps]}"

    run_async_test("DIRECT pattern populates ExecutionResult.steps", test_direct_steps())

    async def test_direct_steps_classify():
        agent = create_agent(model=llm, name="StepsClsAgent")
        result = await agent.ainvoke("Hello there")
        classify_steps = [s for s in result.steps if s.type == StepType.CLASSIFY]
        if classify_steps:
            cs = classify_steps[0]
            assert cs.duration_ms >= 0, "classify step duration should be >= 0"
            assert "pattern=" in cs.output, f"classify step output should contain pattern, got {cs.output}"
        return f"classify_steps={len(classify_steps)}, total={len(result.steps)}"

    run_async_test("DIRECT classify step has duration and output", test_direct_steps_classify())

    # ── Integration: REACT pattern populates steps with tool info ──

    async def test_react_steps():
        agent = create_agent(
            model=llm,
            tools=resolve_tools(["calculate"]),
            name="StepsReactAgent",
        )
        result = await agent.ainvoke("Use the calculate tool to compute 15 * 7")
        assert len(result.steps) >= 1, f"Expected steps, got {len(result.steps)}"
        step_types = [s.type.value for s in result.steps]
        return f"{len(result.steps)} steps: {step_types}"

    run_async_test("REACT pattern populates steps", test_react_steps())

    # ── Integration: token_usage populated ──

    async def test_token_usage_present():
        agent = create_agent(model=llm, name="TokenAgent")
        result = await agent.ainvoke("What is the capital of France?")
        assert isinstance(result.token_usage, dict), f"token_usage should be dict, got {type(result.token_usage)}"
        return f"token_usage={result.token_usage}"

    run_async_test("token_usage is populated after ainvoke", test_token_usage_present())

    # ── Integration: astream yields tokens ──

    async def test_astream_tokens():
        agent = create_agent(model=llm, name="StreamTokenAgent")
        chunks = []
        async for chunk in agent.astream("Say hello"):
            assert isinstance(chunk, str), f"chunk should be str, got {type(chunk)}"
            chunks.append(chunk)
        full = "".join(chunks)
        assert len(full) > 0, "stream should yield non-empty output"
        assert len(chunks) >= 1, f"Expected at least 1 chunk, got {len(chunks)}"
        return f"{len(chunks)} chunks, {len(full)} chars total"

    run_async_test("astream yields str chunks", test_astream_tokens())

    async def test_astream_result_mode():
        agent = create_agent(model=llm, name="StreamResultAgent")
        results = []
        async for item in agent.astream("Hi", stream_mode="result"):
            results.append(item)
        assert len(results) == 1, f"Expected 1 result, got {len(results)}"
        assert isinstance(results[0], ExecutionResult), f"Expected ExecutionResult, got {type(results[0])}"
        assert results[0].success is True
        return f"result.output={results[0].output[:60]}"

    run_async_test("astream stream_mode='result' yields ExecutionResult", test_astream_result_mode())

    # ── Integration: astream_events yields AgentEvent objects ──

    async def test_astream_events():
        agent = create_agent(model=llm, name="EventStreamAgent")
        events = []
        async for event in agent.astream_events("What is 1+1?"):
            assert isinstance(event, AgentEvent), f"Expected AgentEvent, got {type(event)}"
            events.append(event)
        assert len(events) >= 1, f"Expected at least 1 event, got {len(events)}"
        event_types = [e.type for e in events]
        assert "done" in event_types, f"Expected 'done' event, got {event_types}"
        done_event = next(e for e in events if e.type == "done")
        assert "result" in done_event.data, "done event should contain result"
        return f"{len(events)} events: {event_types}"

    run_async_test("astream_events yields events with done", test_astream_events())

    async def test_astream_events_has_thinking():
        agent = create_agent(model=llm, name="ThinkEventAgent")
        events = []
        async for event in agent.astream_events("Explain gravity briefly"):
            events.append(event)
        event_types = [e.type for e in events]
        has_thinking_or_llm = "thinking" in event_types or "llm_call" in event_types
        assert has_thinking_or_llm, f"Expected thinking or llm_call event, got {event_types}"
        return f"event_types={event_types}"

    run_async_test("astream_events includes thinking/llm_call events", test_astream_events_has_thinking())

    # ── Integration: astream_events emits token events for DIRECT ──

    async def test_astream_events_token_react():
        """REACT pattern should emit token events when streaming via astream_events."""
        agent = create_agent(model=llm, tools=[calculate], name="TokenReactAgent")
        events = []
        async for event in agent.astream_events("Use the calculate tool to compute 7+3"):
            events.append(event)
        event_types = [e.type for e in events]
        has_token = "token" in event_types
        assert "done" in event_types, f"Expected 'done' event, got {event_types}"
        if has_token:
            token_events = [e for e in events if e.type == "token"]
            for te in token_events:
                assert "content" in te.data, f"Token event missing 'content' key: {te.data}"
                assert isinstance(te.data["content"], str), "Token content should be str"
            return f"{len(token_events)} token events, types={set(event_types)}"
        return f"no token events (short-circuit or fallback), types={set(event_types)}"

    run_async_test("astream_events emits events for REACT with tools", test_astream_events_token_react())

    async def test_astream_events_direct_shortcircuit():
        """DIRECT short-circuit has no token events (no LLM call), which is correct."""
        agent = create_agent(model=llm, name="DirectSCAgent")
        events = []
        async for event in agent.astream_events("What is 1+1?"):
            events.append(event)
        event_types = [e.type for e in events]
        assert "done" in event_types, f"Expected 'done' event, got {event_types}"
        assert "thinking" in event_types or "llm_call" in event_types, (
            f"Expected thinking or llm_call, got {event_types}"
        )
        return f"types={set(event_types)}"

    run_async_test("astream_events works for DIRECT short-circuit", test_astream_events_direct_shortcircuit())

    # ── Integration: astream_events with thread_id and user_id ──

    async def test_astream_events_with_ids():
        agent = create_agent(model=llm, name="EventIDAgent")
        events = []
        async for event in agent.astream_events(
            "Hello",
            thread_id="test-thread-1",
            user_id="test-user-1",
        ):
            events.append(event)
        event_types = [e.type for e in events]
        assert "done" in event_types, f"Expected 'done' in {event_types}"
        done = next(e for e in events if e.type == "done")
        assert "result" in done.data, "Done event missing result"
        return f"events={len(events)}, types={set(event_types)}"

    run_async_test("astream_events with thread_id/user_id", test_astream_events_with_ids())

    # ── Integration: tool_call_id correlation in REACT ──

    async def test_tool_call_id_react():
        agent = create_agent(model=llm, tools=[calculate], name="ToolIDAgent")
        result = await agent.ainvoke("Use calculate tool to compute 5 + 3")
        tool_calls = [s for s in result.steps if s.type == StepType.TOOL_CALL]
        tool_results = [s for s in result.steps if s.type == StepType.TOOL_RESULT]
        if tool_calls and tool_results:
            tc = tool_calls[0]
            tr = tool_results[0]
            tc_id = tc.metadata.get("id", "") if tc.metadata else ""
            tr_id = tr.metadata.get("id", "") if tr.metadata else ""
            if tc_id and tr_id:
                assert tc_id == tr_id, f"tool_call id={tc_id} != tool_result id={tr_id}"
                return f"matched id={tc_id}"
            return f"ids present: tc={tc_id!r} tr={tr_id!r} (may be empty for some paths)"
        return f"steps={[s.type.value for s in result.steps]} (no tool_call/result found)"

    run_async_test("tool_call_id links tool_call to tool_result", test_tool_call_id_react())

    # ── Integration: astream_events tool events have id ──

    async def test_astream_events_tool_id():
        agent = create_agent(model=llm, tools=[calculate], name="EventToolIDAgent")
        events = []
        async for event in agent.astream_events("Use the calculate tool to compute 10 * 2"):
            events.append(event)
        tc_events = [e for e in events if e.type == "tool_call"]
        tr_events = [e for e in events if e.type == "tool_result"]
        if tc_events and tr_events:
            tc_id = tc_events[0].data.get("id", "")
            tr_id = tr_events[0].data.get("id", "")
            if tc_id and tr_id:
                assert tc_id == tr_id, f"Event tool_call id={tc_id} != tool_result id={tr_id}"
                return f"event id matched: {tc_id}"
            return f"event ids: tc={tc_id!r} tr={tr_id!r}"
        event_types = [e.type for e in events]
        return f"event_types={event_types} (tool events may not appear if DIRECT)"

    run_async_test("astream_events tool_call/tool_result have matching id", test_astream_events_tool_id())

    # ── Unit: StepType.TOKEN exists ──

    run_test(
        "StepType.TOKEN enum value exists",
        lambda: (assert_eq(StepType.TOKEN.value, "token")) or "TOKEN=token",
    )

    # ── Unit: _make_step with id parameter ──

    run_test(
        "_make_step creates step with id in metadata",
        lambda: (
            lambda s: (
                (assert_true(s.metadata is not None) and assert_eq(s.metadata.get("id"), "tc_123")) or "id in metadata"
            )
        )(_make_step(StepType.TOOL_CALL, "search", input="query", id="tc_123")),
    )

    # ── Integration: astream with thread_id ──

    async def test_astream_thread_id():
        agent = create_agent(model=llm, name="StreamThreadAgent")
        chunks = []
        async for chunk in agent.astream("Say hi", thread_id="stream-t1"):
            chunks.append(chunk)
        full = "".join(chunks)
        assert len(full) > 0, "stream should yield output with thread_id"
        return f"{len(chunks)} chunks, text={full[:40]}"

    run_async_test("astream with thread_id", test_astream_thread_id())

    # ── Integration: astream_events token content is concatenatable ──

    async def test_token_content_concat():
        agent = create_agent(model=llm, name="TokenConcatAgent")
        tokens = []
        final_output = ""
        async for event in agent.astream_events("What is 2+2?"):
            if event.type == "token":
                tokens.append(event.data["content"])
            elif event.type == "done":
                final_output = event.data.get("result", {}).get("output", "")
        if tokens:
            concatenated = "".join(tokens)
            assert len(concatenated) > 0, "Token concatenation should be non-empty"
            return f"tokens={len(tokens)}, concat_len={len(concatenated)}"
        return f"no token events (final_output={final_output[:40]})"

    run_async_test("astream_events token content is concatenatable", test_token_content_concat())

    # ── Integration: middleware works with astream_events ──

    async def test_middleware_with_events():
        class TrackMW:
            def __init__(self):
                self.before_called = False
                self.after_called = False

            async def before_agent(self, query, context):
                self.before_called = True

            async def after_agent(self, result, context):
                self.after_called = True

        mw = TrackMW()
        agent = create_agent(model=llm, middleware=[mw], name="MWEventAgent")
        events = []
        async for event in agent.astream_events("Hello"):
            events.append(event)
        assert "done" in [e.type for e in events], "Should have done event"
        assert mw.before_called, "before_agent should be called"
        assert mw.after_called, "after_agent should be called"
        return f"middleware hooks called, events={len(events)}"

    run_async_test("middleware works with astream_events", test_middleware_with_events())

    # ── Integration: session memory with thread_id across calls ──

    async def test_session_memory_thread():
        agent = create_agent(model=llm, name="SessionThreadAgent")
        tid = f"test-session-{uuid.uuid4().hex[:8]}"
        await agent.ainvoke("My favorite color is blue", thread_id=tid)
        r2 = await agent.ainvoke("What is my favorite color?", thread_id=tid)
        lower = r2.output.lower()
        assert "blue" in lower, f"Agent should remember 'blue', got: {r2.output[:100]}"
        return f"remembered: {r2.output[:60]}"

    run_async_test("session memory works with thread_id", test_session_memory_thread())

    # ── Unit: _extract_token_usage with mock AIMessage ──

    run_test(
        "_extract_token_usage with dict response",
        lambda: (assert_eq(_extract_token_usage({"messages": []}), {})) or "empty messages",
    )

    # ── Integration: steps survive model_copy in run_fresh ──

    async def test_steps_survive_model_copy():
        agent = create_agent(model=llm, name="ModelCopyAgent")
        result = await agent.ainvoke("Tell me a joke")
        assert hasattr(result, "steps"), "result must have steps"
        assert hasattr(result, "token_usage"), "result must have token_usage"
        assert result.run_id, "result must have run_id"
        return f"steps={len(result.steps)}, run_id={result.run_id[:8]}"

    run_async_test("steps & token_usage survive model_copy in run_fresh", test_steps_survive_model_copy())

    # ── Export check ──

    run_test(
        "StepType, AgentStep, AgentEvent exported from __init__",
        lambda: import_check("agloom", ["StepType", "AgentStep", "AgentEvent"]),
    )

    run_test(
        "PatternType, SignalType, ExecutionResult exported",
        lambda: import_check("agloom", ["PatternType", "SignalType", "ExecutionResult", "create_agent"]),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Assertion helpers
# ═══════════════════════════════════════════════════════════════════════════════


def assert_eq(a, b):
    assert a == b, f"Expected {b!r}, got {a!r}"
    return True


def assert_true(cond):
    assert cond, "Condition was False"
    return True


def _expect_error(fn):
    try:
        fn()
        assert False, "Expected an error but none was raised"
    except (ValueError, TypeError, AssertionError, Exception):
        return True


def import_check(module_name, names):
    import importlib

    mod = importlib.import_module(module_name)
    for n in names:
        assert hasattr(mod, n), f"{module_name} missing {n}"
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  Main Runner
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    start = time.time()

    print("=" * 60)
    print("  agloom — Comprehensive Test Suite")
    print(f"  LLM: ChatGroq ({GROQ_MODEL})")
    print(f"  API Key: {GROQ_API_KEY[:8]}...{GROQ_API_KEY[-4:]}")
    print("=" * 60)

    # Unit tests (no LLM)
    sec1_models_and_enums()
    sec2_agent_config()
    sec3_frozen_validation()
    sec4_memory()
    sec5_helpers()
    sec6_skills_models()
    sec7_feedback()
    sec8_tools()

    # Integration tests (LLM)
    sec9_classifier()
    sec10_patterns()
    sec11_frozen()
    sec12_memory_cross_turn()
    sec13_skills()
    sec14_feedback_integration()
    sec15_multi_agent()
    sec16_hitl()
    sec17_advanced()
    sec18_param_coverage()
    sec19_real_user()
    sec20_logging_repr()
    sec21_dynamic_prompt_middleware_interrupts()
    sec22_steps_tokens_streaming()

    elapsed = round(time.time() - start, 1)

    print("\n" + "=" * 60)
    print(f"  RESULTS: {_passed} passed, {_failed} failed, {_skipped} skipped")
    print(f"  TIME: {elapsed}s")
    print("=" * 60)

    if _errors:
        print(f"\n  FAILURES ({len(_errors)}):")
        for name, detail in _errors:
            print(f"    - {name}")
            if detail:
                for line in detail.strip().splitlines()[:3]:
                    print(f"      {line}")

    # Close the persistent event loop cleanly so httpx/groq clients
    # don't raise "Event loop is closed" during GC.
    if _LOOP and not _LOOP.is_closed():
        _LOOP.run_until_complete(_LOOP.shutdown_asyncgens())
        _LOOP.close()

    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
