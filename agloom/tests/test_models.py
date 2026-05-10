"""Unit tests for Pydantic models and enums (ported from legacy test suite sec1)."""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from pydantic import ValidationError

from agloom.feedback import EvalScore, RunRecord
from agloom.models import (
    ExecutionResult,
    PatternType,
    QueryAnalysis,
    QueryAnalysisToolPayload,
    ResolvedWorkerConfig,
    Signal,
    SignalType,
    SubTask,
    WorkerPlan,
    WorkerResult,
    query_analysis_from_tool_payload,
)


def _make_result(**overrides: object) -> ExecutionResult:
    defaults: dict = {
        "pattern_used": PatternType.REACT,
        "query": "test query",
        "output": "test output",
        "steps_taken": 2,
        "success": True,
    }
    defaults.update(overrides)
    return ExecutionResult(**defaults)


def _make_score(**overrides: object) -> EvalScore:
    defaults: dict = {
        "accuracy": 0.8,
        "completeness": 0.7,
        "efficiency": 0.9,
        "relevance": 0.85,
        "reasoning": "Good overall performance.",
    }
    defaults.update(overrides)
    return EvalScore(**defaults)


def _make_record(**overrides: object) -> RunRecord:
    defaults: dict = {
        "run_id": uuid.uuid4().hex[:12],
        "agent_name": "TestAgent",
        "query": "test query",
        "pattern_used": "REACT",
        "success": True,
        "output_preview": "test output preview",
    }
    defaults.update(overrides)
    return RunRecord(**defaults)


def test_pattern_type_nine_members() -> None:
    assert len(list(PatternType)) == 9


@pytest.mark.parametrize(
    "name",
    [
        "DIRECT",
        "REACT",
        "SUPERVISOR",
        "PIPELINE",
        "PLANNER_EXECUTOR",
        "REFLECTION",
        "SWARM",
        "BLACKBOARD",
        "HYBRID_DAG",
    ],
)
def test_pattern_type_values(name: str) -> None:
    assert PatternType(name).value == name


@pytest.mark.parametrize("name", ["HALT_ALL", "CLARIFICATION_REQUEST", "SUCCESS", "FAILED"])
def test_signal_type_values(name: str) -> None:
    assert SignalType(name).value == name


def test_subtask_context_flattening() -> None:
    st = SubTask(worker_id="w1", task="t", context=cast("Any", {"k": [1, 2]}))
    assert st.context["k"] == "[1, 2]"


def test_subtask_non_dict_context_empty() -> None:
    st = SubTask(worker_id="w1", task="t", context=cast("Any", "bad"))
    assert st.context == {}


def test_query_analysis_complexity_coercion() -> None:
    qa = QueryAnalysis(pattern=PatternType.DIRECT, complexity="3", reasoning="r")
    assert qa.complexity == 3


def test_query_analysis_complexity_clamped() -> None:
    qa = QueryAnalysis(pattern=PatternType.DIRECT, complexity=0, reasoning="r")
    assert qa.complexity == 0


def test_tool_payload_bool_strings() -> None:
    raw = QueryAnalysisToolPayload(pattern="REACT", can_parallelize="true", needs_reflection="false")
    qa = query_analysis_from_tool_payload(raw)
    assert qa.can_parallelize is True
    assert qa.needs_reflection is False


def test_tool_payload_direct_response_null_string() -> None:
    raw = QueryAnalysisToolPayload(pattern="DIRECT", direct_response="null")
    assert raw.direct_response is None


def test_tool_payload_invalid_pattern_with_tools() -> None:
    raw = QueryAnalysisToolPayload(pattern="INVALID")
    qa = query_analysis_from_tool_payload(raw, tools_available=True)
    assert qa.pattern == PatternType.REACT


def test_tool_payload_invalid_pattern_no_tools() -> None:
    raw = QueryAnalysisToolPayload(pattern="INVALID")
    qa = query_analysis_from_tool_payload(raw, tools_available=False)
    assert qa.pattern == PatternType.DIRECT


def test_tool_payload_reflection_forces_needs_reflection() -> None:
    raw = QueryAnalysisToolPayload(pattern="REFLECTION", needs_reflection="false")
    qa = query_analysis_from_tool_payload(raw)
    assert qa.needs_reflection is True


def test_execution_result_run_id_default() -> None:
    r = ExecutionResult(pattern_used=PatternType.DIRECT, query="q", output="o")
    assert r.run_id == ""


def test_execution_result_run_id_set() -> None:
    r = ExecutionResult(pattern_used=PatternType.DIRECT, query="q", output="o", run_id="abc")
    assert r.run_id == "abc"


def test_execution_result_interrupts_metadata() -> None:
    r = _make_result()
    assert r.interrupts == []
    assert r.metadata == {}


def test_signal_defaults() -> None:
    s = Signal(signal_type=SignalType.SUCCESS, worker_id="w1", message="ok")
    assert s.metadata == {}
    assert s.response_queue is None


def test_worker_result_defaults() -> None:
    wr = WorkerResult(worker_id="w1", task="t", output="o")
    assert wr.signal == SignalType.SUCCESS
    assert wr.error is None
    assert wr.elapsed_ms == 0.0
    assert wr.attempt == 1


def test_evalscore_overall() -> None:
    s = EvalScore(accuracy=0.0, completeness=1.0, efficiency=0.5, relevance=0.5, reasoning="test")
    assert s.overall() == round((0 + 1 + 0.5 + 0.5) / 4, 3)


def test_evalscore_rejects_out_of_range() -> None:
    with pytest.raises(ValidationError):
        EvalScore(
            accuracy=cast("Any", 1.5),
            completeness=0.5,
            efficiency=0.5,
            relevance=0.5,
            reasoning="bad",
        )


def test_evalscore_to_log_str() -> None:
    s = _make_score()
    log = s.to_log_str()
    assert "overall=" in log
    assert "acc=" in log


def test_runrecord_index_text() -> None:
    r = _make_record()
    text = r.index_text()
    assert "query:" in text
    assert "pattern:" in text


def test_runrecord_model_dump_roundtrip() -> None:
    r = _make_record(score=_make_score())
    d = r.model_dump()
    r2 = RunRecord(**d)
    assert r.run_id == r2.run_id
    assert r.score is not None and r2.score is not None
    assert r.score.overall() == r2.score.overall()


def test_worker_plan_flattens_context() -> None:
    wp = WorkerPlan(worker_id="w1", task="t", context=cast("Any", {"k": {"nested": True}}))
    assert isinstance(wp.context["k"], str)


def test_resolved_worker_config_defaults() -> None:
    rc = ResolvedWorkerConfig(worker_id="w1", task="t", system_prompt="p")
    assert rc.tools == []
    assert rc.depends_on == []
    assert rc.max_retries == 2
    assert rc.retry_delay == 1.0
