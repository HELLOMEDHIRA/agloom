"""Recursive orchestration runtime: dispatch, safety, escalation, backward compatibility."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agloom.models import (
    ExecutionResult,
    OrchestrationBudgetExceeded,
    OrchestrationContext,
    OrchestrationCycleDetected,
    PatternType,
    QueryAnalysis,
    SpawnInstruction,
)
from agloom.orchestrator import (
    check_escalation,
    dispatch_pattern,
    evaluate_execution,
    fresh_orchestration_context,
    orchestration_enabled,
    resolve_turn_orchestration,
)
from agloom.models import SpawnedPatternRecord
from agloom.orchestrator.safety import apply_timeout, check_cycle, hash_task


def _agent(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "test",
        "llm": MagicMock(),
        "system_prompt": "You are a test assistant.",
        "tools": [],
        "max_pattern_depth": 3,
        "max_orchestration_llm_calls": 10,
        "max_orchestration_tokens": 0,
        "enable_auto_escalation": False,
        "llm_timeout": 120.0,
        "classifier_timeout": 5.0,
        "structured_max_retries": 0,
    }
    base.update(overrides)
    return base


def _analysis(pattern: PatternType = PatternType.DIRECT) -> QueryAnalysis:
    return QueryAnalysis(pattern=pattern, complexity=3, reasoning="test")


@pytest.mark.asyncio
async def test_orchestration_disabled_when_depth_zero() -> None:
    assert not orchestration_enabled(_agent(max_pattern_depth=0))
    assert orchestration_enabled(_agent(max_pattern_depth=2))
    simple = _analysis(PatternType.DIRECT)
    simple = simple.model_copy(update={"complexity": 2})
    assert not orchestration_enabled(_agent(max_pattern_depth=5), simple)


def test_per_turn_plan_in_fresh_context() -> None:
    analysis = _analysis(PatternType.REACT).model_copy(update={"complexity": 8})
    ctx = fresh_orchestration_context(_agent(max_pattern_depth=5), "q", analysis)
    assert ctx.max_depth == 3
    assert ctx.auto_escalation is False
    plan = resolve_turn_orchestration(
        _agent(max_pattern_depth=5, enable_auto_escalation=True),
        analysis,
    )
    assert plan.max_depth == 3


def test_agent_config_default_max_pattern_depth() -> None:
    from agloom.models import AgentConfig

    cfg = AgentConfig(model="openai:gpt-4o-mini", name="t")
    assert cfg.max_pattern_depth == 0
    assert cfg.enable_orchestration_llm_eval is True


def test_orchestration_runtime_facade() -> None:
    from agloom.orchestrator import OrchestrationRuntime

    agent = _agent(max_pattern_depth=2)
    rt = OrchestrationRuntime(agent)
    assert rt.enabled
    ctx = rt.fresh_context("hello")
    assert ctx.max_depth == 2


@pytest.mark.asyncio
async def test_dispatch_depth_limit() -> None:
    calls = {"n": 0}

    async def _handler(agent: dict, task: Any, analysis: QueryAnalysis, config: dict) -> ExecutionResult:
        calls["n"] += 1
        spawn = config.get("_spawn_api")
        if spawn and calls["n"] < 10:
            await spawn.spawn_pattern(PatternType.DIRECT, "child", reason="chain")
        return ExecutionResult(
            pattern_used=analysis.pattern,
            query=task,
            output="ok",
            success=True,
            analysis=analysis,
        )

    reg = {PatternType.DIRECT: _handler}
    agent = _agent(max_pattern_depth=2, enable_auto_escalation=False)
    agent["registry"] = reg
    instr = SpawnInstruction(pattern=PatternType.DIRECT, task="root")
    result = await dispatch_pattern(agent, instr, analysis=_analysis(PatternType.DIRECT), registry=reg)
    assert "Orchestration stopped" in result.output or result.success


@pytest.mark.asyncio
async def test_cycle_detection_same_pattern_task() -> None:
    task = "identical subtask"
    th = hash_task(task)
    ctx = OrchestrationContext(
        current_depth=1,
        max_depth=5,
        spawned_history=[
            SpawnedPatternRecord(
                spawn_id="a",
                pattern=PatternType.REFLECTION,
                task_hash=th,
                depth=0,
            )
        ],
    )
    with pytest.raises(OrchestrationCycleDetected):
        check_cycle(ctx, PatternType.REFLECTION, th)


def test_context_check_budget_depth() -> None:
    ctx = OrchestrationContext(current_depth=5, max_depth=5)
    with pytest.raises(OrchestrationBudgetExceeded):
        ctx.check_budget()


@pytest.mark.asyncio
async def test_evaluate_execution_failure_low_confidence() -> None:
    agent = _agent(enable_orchestration_llm_eval=False)
    ctx = fresh_orchestration_context(agent, "q")
    result = ExecutionResult(
        pattern_used=PatternType.REACT,
        query="q",
        output="",
        success=False,
        error="boom",
    )
    instr = SpawnInstruction(pattern=PatternType.REACT, task="q")
    ev = await evaluate_execution(agent, result, instr, ctx)
    assert ev.failure_detected
    assert ev.confidence < 0.5
    assert ev.evaluation_source == "fallback"


@pytest.mark.asyncio
async def test_evaluate_execution_uses_llm_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agloom.orchestrator.evaluation import OrchestrationEvalScore

    async def _fake_structured(*_a: Any, **_k: Any) -> OrchestrationEvalScore:
        return OrchestrationEvalScore(
            confidence=0.82,
            quality_score=0.79,
            has_conflicts=False,
            failure_detected=False,
            reasoning="solid answer",
        )

    monkeypatch.setattr(
        "agloom.llm_utils.robust_structured_call",
        _fake_structured,
    )
    agent = _agent(enable_orchestration_llm_eval=True)
    ctx = fresh_orchestration_context(agent, "q")
    result = ExecutionResult(
        pattern_used=PatternType.DIRECT,
        query="q",
        output="A complete answer with enough substance.",
        success=True,
    )
    instr = SpawnInstruction(pattern=PatternType.DIRECT, task="q")
    ev = await evaluate_execution(agent, result, instr, ctx)
    assert ev.evaluation_source == "llm"
    assert ev.confidence == pytest.approx(0.82)


@pytest.mark.asyncio
async def test_escalation_react_failure_spawns_reflection() -> None:
    agent = _agent(enable_auto_escalation=True)
    ctx = fresh_orchestration_context(agent, "q")
    ctx = ctx.model_copy(update={"max_depth": 5, "current_depth": 0})
    result = ExecutionResult(
        pattern_used=PatternType.REACT,
        query="q",
        output="failed",
        success=False,
        error="tool error",
    )
    instr = SpawnInstruction(pattern=PatternType.REACT, task="find papers")
    from agloom.orchestrator.evaluation import ExecutionEvaluation

    evaluation = ExecutionEvaluation(
        confidence=0.2,
        quality_score=0.2,
        failure_detected=True,
    )
    spawns = await check_escalation(agent, result, evaluation, instr, ctx)
    assert len(spawns) == 1
    assert spawns[0].pattern == PatternType.REFLECTION


@pytest.mark.asyncio
async def test_dispatch_merges_escalation_child(monkeypatch: pytest.MonkeyPatch) -> None:
    from agloom.orchestrator.evaluation import OrchestrationEvalScore

    async def _fake_structured(*_a: Any, **_k: Any) -> OrchestrationEvalScore:
        return OrchestrationEvalScore(
            confidence=0.2,
            quality_score=0.2,
            failure_detected=True,
            suggested_pattern="REFLECTION",
            escalation_reason="react_failure_recovery",
            reasoning="failed",
        )

    monkeypatch.setattr(
        "agloom.llm_utils.robust_structured_call",
        _fake_structured,
    )
    call_count = {"n": 0}

    async def _handler(agent: dict, task: Any, analysis: QueryAnalysis, config: dict) -> ExecutionResult:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ExecutionResult(
                pattern_used=PatternType.REACT,
                query=task,
                output="partial result without enough recovery detail yet",
                success=False,
                error="fail",
            )
        return ExecutionResult(
            pattern_used=PatternType.REFLECTION,
            query=task,
            output="recovered",
            success=True,
        )

    reg = {PatternType.REACT: _handler, PatternType.REFLECTION: _handler}
    agent = _agent(max_pattern_depth=5, enable_auto_escalation=True)
    agent["registry"] = reg
    hard = _analysis(PatternType.REACT).model_copy(
        update={"complexity": 8, "orchestration_auto_escalation": True}
    )

    instr = SpawnInstruction(pattern=PatternType.REACT, task="search arxiv")
    result = await dispatch_pattern(
        agent,
        instr,
        analysis=hard,
        registry=reg,
    )
    assert "recovered" in result.output
    assert call_count["n"] >= 2


def test_timeout_propagation_decays() -> None:
    agent = _agent()
    ctx = OrchestrationContext(current_depth=2)
    t = apply_timeout(agent, ctx)
    assert 15.0 <= t < 120.0


@pytest.mark.asyncio
async def test_trace_recorded_in_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from agloom.orchestrator.evaluation import OrchestrationEvalScore

    async def _fake_structured(*_a: Any, **_k: Any) -> OrchestrationEvalScore:
        return OrchestrationEvalScore(
            confidence=0.9,
            quality_score=0.88,
            failure_detected=False,
            reasoning="ok",
        )

    monkeypatch.setattr(
        "agloom.llm_utils.robust_structured_call",
        _fake_structured,
    )

    async def _handler(agent: dict, task: Any, analysis: QueryAnalysis, config: dict) -> ExecutionResult:
        return ExecutionResult(
            pattern_used=analysis.pattern,
            query=task,
            output="done",
            success=True,
        )

    reg = {PatternType.DIRECT: _handler}
    agent = _agent(max_pattern_depth=3)
    agent["registry"] = reg
    instr = SpawnInstruction(pattern=PatternType.DIRECT, task="hello")
    result = await dispatch_pattern(
        agent,
        instr,
        analysis=_analysis(PatternType.DIRECT),
        registry=reg,
    )
    trace = result.metadata.get("orchestration_trace")
    assert isinstance(trace, list)
    assert any(s.get("action") == "enter" for s in trace)
    complete = [s for s in trace if s.get("action") == "complete"]
    assert complete
    assert complete[0].get("confidence") == pytest.approx(0.9)


def test_fresh_context_budget_fields() -> None:
    agent = _agent(max_pattern_depth=4, max_orchestration_tokens=5000)
    ctx = fresh_orchestration_context(agent, "root q")
    assert ctx.max_depth == 4
    assert ctx.max_total_tokens == 5000


def test_detect_perspective_conflict() -> None:
    from agloom.orchestrator.hooks import detect_perspective_conflict

    a = " ".join(["async messaging event driven architecture"] * 8)
    b = " ".join(["synchronous grpc performance low latency"] * 8)
    assert detect_perspective_conflict([a, b])
    assert not detect_perspective_conflict([a, a])


@pytest.mark.asyncio
async def test_recover_failed_workers_replaces_failure() -> None:
    from agloom.orchestrator.hooks import recover_failed_workers
    from agloom.models import SignalType, WorkerResult

    async def _spawn(pattern, task, **kwargs):
        return ExecutionResult(
            pattern_used=pattern,
            query=task,
            output="recovered output",
            success=True,
        )

    spawn_api = MagicMock()
    spawn_api.spawn_pattern = AsyncMock(side_effect=_spawn)
    config = {"_spawn_api": spawn_api}
    agent = _agent(enable_pattern_spawns=True)
    failed = WorkerResult(
        worker_id="w1",
        task="do work",
        output="err",
        signal=SignalType.FAILED,
    )
    out = await recover_failed_workers(agent, config, [failed])
    assert out[0].signal == SignalType.SUCCESS
    assert "recovered" in out[0].output


@pytest.mark.asyncio
async def test_maybe_recover_react_failure() -> None:
    from agloom.orchestrator.hooks import maybe_recover_react_failure

    spawn_api = MagicMock()
    spawn_api.spawn_pattern = AsyncMock(
        return_value=ExecutionResult(
            pattern_used=PatternType.REFLECTION,
            query="q",
            output="reflection ok",
            success=True,
        )
    )
    agent = _agent(enable_pattern_spawns=True)
    config = {"_spawn_api": spawn_api}
    failed = ExecutionResult(
        pattern_used=PatternType.REACT,
        query="q",
        output="fail",
        success=False,
    )
    recovered = await maybe_recover_react_failure(
        agent, config, "q", _analysis(PatternType.REACT), failed
    )
    assert recovered.success
    assert recovered.metadata.get("orchestration_react_recovery")


@pytest.mark.asyncio
async def test_detect_conflicts_via_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from agloom.orchestrator.evaluation import ConflictEvalScore, detect_conflicts_via_llm

    async def _fake_structured(*_a: Any, **_k: Any) -> ConflictEvalScore:
        return ConflictEvalScore(has_conflicts=True, reasoning="contradictory claims")

    monkeypatch.setattr(
        "agloom.llm_utils.robust_structured_call",
        _fake_structured,
    )
    agent = _agent(enable_orchestration_llm_eval=True)
    long_a = "use async event-driven messaging architecture " * 3
    long_b = "use synchronous grpc with low latency only " * 3
    assert await detect_conflicts_via_llm(agent, "pick a stack", [long_a, long_b])


def test_translator_orchestration_event() -> None:
    from agloom.models import AgentEvent
    from agloom.protocol import SessionEmitter
    from agloom.runtime.translator import translate

    captured: list[str] = []
    emitter = SessionEmitter(session="s1", thread="t1")
    emitter._write = lambda evt: captured.append(evt.type)  # type: ignore[method-assign, assignment]
    translate(
        AgentEvent(
            type="orchestration",
            data={
                "depth": 1,
                "pattern": "REFLECTION",
                "action": "enter",
                "reason": "worker_failure_recovery",
            },
        ),
        emitter,
    )
    assert captured == ["orchestration.step"]
