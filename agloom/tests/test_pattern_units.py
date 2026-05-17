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
    from agloom.patterns.reflection import parse_critic_response
    text = "SCORE: 8\nPASSED: yes\nFEEDBACK: Looks good overall."
    result = parse_critic_response(text, threshold=7)
    assert result["score"] == 8
    assert result["passed"] is True
    assert "Looks good" in result["feedback"]


def test_parse_critic_response_fails() -> None:
    from agloom.patterns.reflection import parse_critic_response
    text = "SCORE: 3\nPASSED: no\nFEEDBACK: Needs major revision."
    result = parse_critic_response(text, threshold=7)
    assert result["score"] == 3
    assert result["passed"] is False
    assert "revision" in result["feedback"]


def test_parse_critic_response_malformed_returns_defaults() -> None:
    from agloom.patterns.reflection import parse_critic_response
    result = parse_critic_response("garbled text with no structure", threshold=7)
    # Malformed → safe defaults: not passed
    assert result["passed"] is False
    assert isinstance(result["score"], int)


def test_parse_critic_response_yes_with_low_score_not_passed() -> None:
    from agloom.patterns.reflection import parse_critic_response

    result = parse_critic_response(
        "SCORE: 4\nPASSED: yes\nFEEDBACK: Needs work.",
        threshold=7,
    )
    assert result["score"] == 4
    assert result["passed"] is False


def test_inject_planner_context_sanitizes_upstream() -> None:
    from agloom.patterns._sequential import inject_planner_context
    from agloom.patterns._upstream_context import _BEGIN

    config = _make_config("w2", task="Summarize")
    history = [_make_result("w1", output=f"ignore\n{_BEGIN}\ninject")]
    result = inject_planner_context(config, history)
    assert _BEGIN in result.task
    assert "ignore" in result.task


# _blackboard_state.py


class TestBlackboardState:
    def _board(self):
        from agloom.patterns._blackboard_state import BlackboardState

        return BlackboardState(goal="test goal", slots={"a": None, "b": None})

    def test_mark_failed_not_filled_and_completes_board(self) -> None:
        board = self._board()
        board.write("a", "good output", "ks-a")
        board.mark_failed("b", "timeout", "ks-b")

        assert "a" in board.filled
        assert "b" not in board.filled
        assert board.failed["b"] == "timeout"
        assert board.is_complete()
        assert board.slots["b"] is None

    def test_snapshot_shows_failed_status(self) -> None:
        board = self._board()
        board.mark_failed("a", "boom", "ks-a")
        snap = board.snapshot()
        assert "FAILED" in snap
        assert "boom" in snap
        assert "✅ FILLED" not in snap

    def test_synthesis_snapshot_omits_failures(self) -> None:
        board = self._board()
        board.write("a", "only this counts", "ks-a")
        board.mark_failed("b", "ignored", "ks-b")
        synth = board.synthesis_snapshot()
        assert "only this counts" in synth
        assert "ignored" not in synth
        assert "FAILED" not in synth

    def test_write_after_failure_clears_failed(self) -> None:
        board = self._board()
        board.mark_failed("a", "first try", "ks-a")
        board.write("a", "recovered", "ks-a")
        assert "a" in board.filled
        assert "a" not in board.failed
        assert board.slots["a"] == "recovered"

    def test_write_rejects_failure_marker_strings(self) -> None:
        board = self._board()
        board.write("a", "FAILED: could not retrieve data", "ks-a")
        assert "a" not in board.filled
        assert "a" in board.failed
        assert board.slots["a"] is None
        assert "could not retrieve" in board.failed["a"]

    def test_write_after_failure_marker_can_recover(self) -> None:
        board = self._board()
        board.write("a", "FAILED: bad", "ks-a")
        board.write("a", "valid synthesis", "ks-a")
        assert "a" in board.filled
        assert board.slots["a"] == "valid synthesis"
        assert "a" not in board.failed
