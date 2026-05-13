"""Unit tests for pure functions in agloom pattern modules.

Tests cover stateless helper functions that require no LLM or async context.
Pattern integration tests (involving actual agents) live in higher-level suites.
"""

from __future__ import annotations

import pytest

from agloom.models import ResolvedWorkerConfig, SignalType, WorkerResult
from agloom.patterns._sequential import (
    inject_pipeline_input,
    inject_planner_context,
    topological_sort,
)

# _sequential.py


def _make_config(worker_id: str, task: str = "do work", depends_on: list[str] | None = None) -> ResolvedWorkerConfig:
    return ResolvedWorkerConfig(
        worker_id=worker_id,
        task=task,
        system_prompt="You are a helpful assistant.",
        depends_on=depends_on or [],
    )


def _make_result(worker_id: str, output: str = "result", task: str = "do work") -> WorkerResult:
    return WorkerResult(
        worker_id=worker_id,
        output=output,
        task=task,
        signal=SignalType.SUCCESS,
        steps=[],
    )


class TestInjectPipelineInput:
    def test_appends_previous_output_to_task(self) -> None:
        config = _make_config("w2", task="Summarize")
        prev = _make_result("w1", output="Here is some text", task="Generate")
        result = inject_pipeline_input(config, prev)
        assert "Here is some text" in result.task
        assert "w1" in result.task

    def test_original_config_not_mutated(self) -> None:
        config = _make_config("w2", task="Summarize")
        prev = _make_result("w1", output="text")
        inject_pipeline_input(config, prev)
        assert config.task == "Summarize"


class TestInjectPlannerContext:
    def test_empty_history_returns_unchanged(self) -> None:
        config = _make_config("w1", task="Do something")
        result = inject_planner_context(config, [])
        assert result.task == "Do something"

    def test_history_included_in_task(self) -> None:
        config = _make_config("w3", task="Finalize")
        history = [
            _make_result("w1", output="first output"),
            _make_result("w2", output="second output"),
        ]
        result = inject_planner_context(config, history)
        assert "first output" in result.task
        assert "second output" in result.task
        assert "w1" in result.task
        assert "w2" in result.task

    def test_original_config_not_mutated(self) -> None:
        config = _make_config("w3", task="Finalize")
        history = [_make_result("w1", output="out")]
        inject_planner_context(config, history)
        assert config.task == "Finalize"


class TestTopologicalSort:
    def test_linear_chain(self) -> None:
        configs = [
            _make_config("c", depends_on=["b"]),
            _make_config("a"),
            _make_config("b", depends_on=["a"]),
        ]
        result = topological_sort(configs)
        ids = [c.worker_id for c in result]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_no_dependencies_any_order_ok(self) -> None:
        configs = [_make_config("x"), _make_config("y"), _make_config("z")]
        result = topological_sort(configs)
        assert {c.worker_id for c in result} == {"x", "y", "z"}

    def test_diamond_dependency(self) -> None:
        configs = [
            _make_config("d", depends_on=["b", "c"]),
            _make_config("b", depends_on=["a"]),
            _make_config("c", depends_on=["a"]),
            _make_config("a"),
        ]
        result = topological_sort(configs)
        ids = [c.worker_id for c in result]
        assert ids.index("a") < ids.index("b")
        assert ids.index("a") < ids.index("c")
        assert ids.index("b") < ids.index("d")
        assert ids.index("c") < ids.index("d")

    def test_cycle_raises(self) -> None:
        configs = [
            _make_config("a", depends_on=["b"]),
            _make_config("b", depends_on=["a"]),
        ]
        with pytest.raises(ValueError, match="Circular dependency"):
            topological_sort(configs)

    def test_unknown_dependency_raises(self) -> None:
        configs = [_make_config("a", depends_on=["nonexistent"])]
        with pytest.raises(ValueError, match="unknown worker"):
            topological_sort(configs)

    def test_single_worker_no_deps(self) -> None:
        configs = [_make_config("solo")]
        result = topological_sort(configs)
        assert len(result) == 1
        assert result[0].worker_id == "solo"

    def test_empty_list(self) -> None:
        assert topological_sort([]) == []


# reflection.py — parse_critic_response


def test_parse_critic_response_passes() -> None:
    from agloom.patterns.reflection import _parse_critic_response  # type: ignore[attr-defined]
    text = "SCORE: 8\nPASSED: yes\nFEEDBACK: Looks good overall."
    result = _parse_critic_response(text, threshold=7)
    assert result["score"] == 8
    assert result["passed"] is True
    assert "Looks good" in result["feedback"]


def test_parse_critic_response_fails() -> None:
    from agloom.patterns.reflection import _parse_critic_response  # type: ignore[attr-defined]
    text = "SCORE: 3\nPASSED: no\nFEEDBACK: Needs major revision."
    result = _parse_critic_response(text, threshold=7)
    assert result["score"] == 3
    assert result["passed"] is False
    assert "revision" in result["feedback"]


def test_parse_critic_response_malformed_returns_defaults() -> None:
    from agloom.patterns.reflection import _parse_critic_response  # type: ignore[attr-defined]
    result = _parse_critic_response("garbled text with no structure", threshold=7)
    # Malformed → safe defaults: not passed
    assert result["passed"] is False
    assert isinstance(result["score"], int)
